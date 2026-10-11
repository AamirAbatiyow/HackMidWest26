"""Vouch service: vendor master, runs, and the stage functions the Strands graph executes.

Stages (graph node ids in brackets):
  [intake]      submissions -> Invoice records (regex parser first; LLM quotes verified against the source)
  [resolve]     deterministic vendor resolution: known / new / uncertain (tax id, domain, fuzzy name,
                embeddings as a re-ranker, bank account)
  [sender]      deterministic email sender check: SPF/DKIM/DMARC, lookalike domains, reply-to mismatch
  [kernel]      deterministic checks against the master file, credit netting, ring links
  [score]       risk model + LIME (inference service / local torch / heuristic)
  [investigate] class-specific investigator agents on flagged cards (advisory only)
  [policy]      Cedar-style policy -> FAST_PAY / STANDARD / HOLD
  [funding]     pay-now vs schedule from the cash forecast
  [explain]     owner-facing explanation, provenance-checked, template fallback
  [fast_pay]    settles FAST_PAY cards under the owner's standing rule
  [settle]      owner approval interrupt (hook) -> policy re-check -> batch settlement
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from hm_core.errors import NotFoundError, ValidationFailedError
from hm_settlement import PaymentRequest, SettlementAdapter, get_adapter
from vouch.agents import (
    EXPLAINER_PROMPT,
    INTAKE_PROMPT,
    INVESTIGATOR_PROMPTS,
    Explanations,
    IntakeExtraction,
    InvestigationReport,
)
from vouch.cards import Investigation, PaymentCard, now_iso
from vouch.config import Settings, get_settings
from vouch.contracts import EmailEnvelope, SenderFindings, VendorClaim, email_domain
from vouch.decider.classify import IntakeClassification, IntakeClassifier, probes_from_submission
from vouch.decider.client import DeciderClient
from vouch.decider.intervention import GroundingIntervention
from vouch.domain import CardStatus, Invoice, Lane, LineItem, PastPayment, Resolution, Vendor
from vouch.features import invoice_features
from vouch.funding import CashForecast, recommend
from vouch.graph_features import VendorGraph
from vouch.intake.claims import extract_claim
from vouch.intake.email_parse import envelope_from_headers
from vouch.kernel import (
    FactSheet,
    Limits,
    MoneyParseError,
    _norm_invoice_number,
    allocate_credits,
    batch_totals,
    check_invoice,
    format_cents,
    normalize_account,
    parse_cents,
    parse_date,
    parse_invoice_text,
)
from vouch.llm import LLMRuntime
from vouch.policy import build_policy, evaluate_batch, evaluate_card
from vouch.provenance import check_provenance
from vouch.scorer import HeuristicScorer, Scorer, get_scorer
from vouch.sender import check_sender
from vouch.timing import card_step
from vouch.vendors import VendorDirectory, resolve_vendor

log = logging.getLogger(__name__)


class Submission(BaseModel):
    """One invoice as submitted by the owner/AP inbox: structured JSON fields and/or raw (PDF) text.

    Email intake adds the message headers (From, Reply-To, Authentication-Results, ...) so the sender
    check can run; file uploads carry the document hashes for the audit trail.
    """

    model_config = ConfigDict(extra="allow")

    text: str | None = Field(None, description="Raw invoice or PDF-extracted text")
    headers: dict[str, str] = Field(default_factory=dict, description="Email headers when received by mail")
    source: Literal["json", "text", "email", "upload"] | None = Field(
        None, description="How the invoice arrived (defaults to json/text)"
    )
    received_at: str | None = None
    documents: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Extracted documents: filename, kind, sha256, extractor (+ tool, fallback when the "
        "intake service chose the extractor from the tool decision)",
    )
    routing: dict[str, Any] | None = Field(
        None,
        description="Decision chain settled before extraction by the intake service (an "
        "IntakeClassification); the engine completes it instead of asking a model again. Never "
        "accepted from API clients.",
    )
    vendor_id: str | None = None
    vendor_name: str | None = None
    invoice_number: str | None = None
    amount: str | None = Field(None, description='Money string, e.g. "12,480.00"; parsed by the kernel')
    amount_cents: int | None = None
    currency: str = "USD"
    issue_date: date | None = None
    due_date: date | None = None
    po_number: str | None = None
    delivery_confirmed: bool = False
    bank_account: str | None = None
    remit_email: str | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    is_credit_note: bool = False
    submitted_by: str = "ap-inbox"
    discount_bps: int = 0
    discount_days: int = 0
    amount_origin: Literal["source", "llm"] = "source"


@dataclass
class Run:
    id: str
    submissions: list[Submission]
    created_at: str = field(default_factory=now_iso)
    status: str = "created"  # created, running, awaiting_approval, completed, failed
    label: str = ""
    cards: dict[str, PaymentCard] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    node_ms: dict[str, float] = field(default_factory=dict)
    pending: dict[str, Any] | None = None  # owner-approval interrupt awaiting a response
    approval: dict[str, Any] | None = None
    settlements: list[dict[str, Any]] = field(default_factory=list)
    graph: Any = None
    error: str | None = None
    llm_calls_before: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def emit(self, kind: str, **data: Any) -> None:
        with self._lock:
            self.events.append({"seq": len(self.events) + 1, "at": now_iso(), "type": kind, **data})

    def card_list(self) -> list[PaymentCard]:
        return list(self.cards.values())


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _quote_in_source(quote: str | None, source: str) -> bool:
    return bool(quote) and _squash(quote) in _squash(source)


def _mask(account: str | None) -> str:
    acct = normalize_account(account) or ""
    return f"****{acct[-4:]}" if acct else "none"


class VouchEngine:
    def __init__(
        self,
        settings: Settings | None = None,
        llm: LLMRuntime | None = None,
        adapter: SettlementAdapter | None = None,
        scorer: Scorer | None = None,
        today: date | None = None,
        decider: DeciderClient | None = None,
    ):
        self.settings = settings or get_settings()
        s = self.settings
        self.limits = Limits(
            approval_limit_cents=s.approval_limit_cents,
            fast_pay_limit_cents=s.fast_pay_limit_cents,
            single_payment_limit_cents=s.single_payment_limit_cents,
            batch_limit_cents=s.batch_limit_cents,
        )
        self.policy = build_policy(self.limits)
        self.llm = llm or LLMRuntime.from_settings(s)
        # Advisory intake routing: Strands Decider when DECIDER_ENABLED (or a client is injected), else the
        # deterministic sniffing route. It never touches amounts, lanes or scores.
        self.classifier = IntakeClassifier.from_settings(s, llm=self.llm, client=decider)
        self._adapter = adapter
        self._scorer = scorer
        self.today = today or date.today()
        self.forecast = CashForecast(
            opening_balance_cents=s.opening_balance_cents, buffer_cents=s.cash_buffer_cents
        )
        self.vendors: dict[str, Vendor] = {}
        self.graph = VendorGraph.build([])
        self.directory = VendorDirectory()
        self.embedding_index: Any = None  # vouch.vendors.embeddings.EmbeddingIndex, set by the service
        self.runs: dict[str, Run] = {}
        self.timings: dict[str, list[float]] = {}
        self.lock = threading.RLock()
        # Persistence hook (set by the service): called with the run after every node and owner action.
        self.on_change: Callable[[Run], None] | None = None
        self.on_vendors_changed: Callable[[list[Vendor]], None] | None = None

    # -- wiring --------------------------------------------------------------------------------------

    @property
    def adapter(self) -> SettlementAdapter:
        if self._adapter is None:
            self._adapter = get_adapter()
        return self._adapter

    def scorer(self) -> Scorer:
        return self._scorer or get_scorer(self.settings)

    def load_vendors(self, vendors: list[Vendor], replace: bool = False) -> None:
        with self.lock:
            if replace:
                self.vendors = {}
            for v in vendors:
                self.vendors[v.id] = v
            self.graph = VendorGraph.build(list(self.vendors.values()))
            self.directory = VendorDirectory(list(self.vendors.values()))
        if self.on_vendors_changed:
            self.on_vendors_changed(vendors)

    def time(self, key: str, ms: float) -> None:
        self.timings.setdefault(key, []).append(ms)

    def changed(self, run: Run) -> None:
        if self.on_change:
            try:
                self.on_change(run)
            except Exception as exc:  # persistence must never break a payment run
                log.warning("persistence hook failed for %s: %s", run.id, exc)

    def new_run(self, submissions: list[Submission], label: str = "") -> Run:
        for k, sub in enumerate(submissions, start=1):
            if sub.amount and sub.amount_cents is None:
                try:
                    parse_cents(sub.amount)
                except MoneyParseError as exc:
                    raise ValidationFailedError(f"invoice {k}: {exc}") from exc
            if not sub.text and not (sub.vendor_id or sub.vendor_name):
                raise ValidationFailedError(f"invoice {k}: needs text, vendor_id, or vendor_name")
        run = Run(id=f"run_{uuid.uuid4().hex[:8]}", submissions=submissions, label=label)
        run.llm_calls_before = self.llm.stats.calls
        self.runs[run.id] = run
        return run

    def find_card(self, card_id: str) -> tuple[Run, PaymentCard]:
        for run in self.runs.values():
            if card_id in run.cards:
                return run, run.cards[card_id]
        raise NotFoundError(f"unknown card {card_id}")

    def match_vendor(self, vendor_id: str | None, name: str | None) -> Vendor | None:
        """Exact id first, otherwise the deterministic resolver (fuzzy name only, as a convenience)."""
        if vendor_id and vendor_id in self.vendors:
            return self.vendors[vendor_id]
        if not name:
            return None
        res = resolve_vendor(VendorClaim(name=name), self.directory)
        return self.vendors.get(res.vendor_id or "") if res.status == "known" else None

    # -- [resolve] -----------------------------------------------------------------------------------

    def _envelope(self, sub: Submission) -> EmailEnvelope | None:
        return envelope_from_headers(sub.headers) if sub.headers else None

    def resolve_vendors(self, run: Run) -> None:
        """Deterministic vendor resolution for every card; replaces name-only matching."""
        embedder = self.llm.embedder_or_none() if self.embedding_index is not None else None
        for k, card in enumerate(run.card_list()):
            inv, sub = card.invoice, run.submissions[k] if k < len(run.submissions) else None
            env = self._envelope(sub) if sub else None
            with card_step(card, "screen"):
                claim = extract_claim(inv.raw_text, sender_email=env.from_addr if env else None)
                claim.name = inv.vendor_name if inv.vendor_name != "unknown vendor" else claim.name
                claim.bank_account = inv.bank_account or claim.bank_account
                claim.email = inv.remit_email or claim.email
                res = resolve_vendor(
                    claim,
                    self.directory,
                    vendor_id=inv.vendor_id or (sub.vendor_id if sub else None),
                    sender_domain=email_domain(env.from_addr) if env else None,
                    embedder=embedder,
                    index=self.embedding_index,
                )
            card.resolution = res
            if res.status == "known" and res.vendor_id:
                inv.vendor_id = res.vendor_id
                inv.vendor_name = res.vendor_name
            else:
                inv.vendor_id = None  # an unverified claim never inherits a master-file identity
            card.log(
                "vendor_resolved", status=res.status, matched_on=res.matched_on, confidence=res.confidence
            )
            for note in res.notes:
                card.log("resolution_note", note=note)
        run.emit(
            "vendors_resolved",
            known=sum(c.resolution.status == "known" for c in run.card_list() if c.resolution),
            new=sum(c.resolution.status == "new" for c in run.card_list() if c.resolution),
            uncertain=sum(c.resolution.status == "uncertain" for c in run.card_list() if c.resolution),
        )

    # -- [sender] ------------------------------------------------------------------------------------

    def sender_check(self, run: Run) -> None:
        """Deterministic email sender check; runs before any detector or LLM sees the card."""
        vendors = list(self.vendors.values())
        for k, card in enumerate(run.card_list()):
            sub = run.submissions[k] if k < len(run.submissions) else None
            env = self._envelope(sub) if sub else None
            claimed = self.vendors.get(card.invoice.vendor_id or "")
            with card_step(card, "sender"):
                findings: SenderFindings = check_sender(env, vendors, claimed)
            card.sender = findings
            if findings.checked:
                card.log(
                    "sender_checked", flags=findings.flags, risk=findings.risk, auth_pass=findings.auth_pass
                )
        run.emit(
            "sender_checked",
            checked=sum(bool(c.sender and c.sender.checked) for c in run.card_list()),
            suspicious=sum(bool(c.sender and c.sender.suspicious) for c in run.card_list()),
        )

    # -- [intake] ------------------------------------------------------------------------------------

    def intake(self, run: Run) -> None:
        for k, sub in enumerate(run.submissions, start=1):
            card_id = f"{run.id}.{k}"
            llm_before = self.llm.stats.by_role.get("intake", {}).get("calls", 0)
            t0 = time.perf_counter()
            try:
                inv, notes = self._intake_one(card_id, sub)
            except (MoneyParseError, ValueError) as exc:
                raise ValidationFailedError(f"submission {k}: {exc}") from exc
            read_ms = (time.perf_counter() - t0) * 1000
            llm_calls = int(self.llm.stats.by_role.get("intake", {}).get("calls", 0) - llm_before)
            extra = sorted((sub.model_extra or {}).keys())
            card = PaymentCard(id=card_id, run_id=run.id, invoice=inv)
            card.step_ms["read"] = round(read_ms, 3)
            card.log(
                "intake_read",
                parser="kernel" if sub.text else "structured_fields",
                llm_calls=llm_calls,
                model=self.llm.model_name if llm_calls else None,
                amount_origin=inv.amount_origin,
                documents=len(sub.documents),
            )
            if extra:
                card.log(
                    "ignored_fields", fields=extra, note="unknown fields never influence payment decisions"
                )
            for note in notes:
                card.log("intake_note", note=note)
            if sub.text or sub.documents:
                with card_step(card, "format"):
                    self._classify_intake(run, card, sub)
            run.cards[card_id] = card
            run.emit("card_created", card_id=card_id, vendor=inv.vendor_name, source=inv.source)

    @staticmethod
    def missing_required_fields(card: PaymentCard, sub: Submission) -> list[str]:
        """Required invoice fields the kernel could not find in the document (structured fields count)."""
        inv = card.invoice
        missing: list[str] = []
        if inv.vendor_name == "unknown vendor" and not (sub.vendor_id or sub.vendor_name):
            missing.append("vendor_name")
        if inv.invoice_number.startswith("UNNUMBERED-") and not sub.invoice_number:
            missing.append("invoice_number")
        if inv.amount_cents <= 0 and sub.amount_cents is None and not sub.amount:
            missing.append("amount")
        return missing

    def _classify_intake(self, run: Run, card: PaymentCard, sub: Submission) -> None:
        """Advisory routing for submissions that carry a document or text (never for pure JSON fields).

        The decision chain (format -> extraction tool -> kickback reason) is recorded on the card, one
        timeline entry per decision, and surfaced in the payment view; a kickback only adds a hold whose
        draft email the owner must approve. Any failure leaves the card as is.

        The live intake service settles the chain *before* extraction and picks the extractor from the tool
        decision (``sub.routing``); here that chain is completed with what extraction revealed (no second
        model call). Submissions that arrive with text or documents only are classified after the fact.
        """
        try:
            probes = probes_from_submission(sub.documents, sub.text)
            attachments = [d for d in sub.documents if d.get("extractor") and d.get("kind") != "email_body"]
            # The extractor the chain actually chose, when the service applied one; else the first attachment's.
            routed = [d for d in attachments if d.get("tool") and not d.get("fallback")]
            extractor = next((str(d["extractor"]) for d in routed or attachments), None)
            missing = self.missing_required_fields(card, sub)
            if sub.routing:
                prior = IntakeClassification.model_validate(sub.routing)
                cls = self.classifier.complete(
                    prior,
                    probes,
                    self._envelope(sub),
                    source=sub.source or "text",
                    extractor_used=extractor,
                    missing_fields=missing,
                )
            else:
                cls = self.classifier.classify(
                    probes,
                    self._envelope(sub),
                    source=sub.source or "text",
                    extractor_used=extractor,
                    missing_fields=missing,
                )
        except Exception as exc:  # routing is advisory; it must never break intake
            log.warning("intake classification failed for %s: %s", card.id, exc)
            card.log("intake_classification_failed", error=f"{type(exc).__name__}: {exc}")
            return
        card.intake = cls
        for d in sub.documents:
            if "tool" in d:  # the service chose the extractor from the tool decision: one entry per file
                card.log(
                    "document_extracted",
                    filename=d.get("filename"),
                    kind=d.get("kind"),
                    extractor=d.get("extractor"),
                    tool=d.get("tool"),
                    fallback=d.get("fallback"),
                    warnings=list(d.get("warnings") or []),
                )
        for d in cls.decisions:
            card.log(
                "intake_decision",
                key=d.key,
                question=d.question,
                options=list(d.options),
                answer=d.answer,
                reason_code=d.reason_code,
                accepted=d.accepted,
                engine=d.engine,
                confidence=d.confidence,
                latency_ms=d.latency_ms,
                input_tokens=d.input_tokens,
                output_tokens=d.output_tokens,
                attempts=d.attempts,
                validation_errors=list(d.validation_errors),
                error=d.error,
                note=d.note,
            )
        card.log(
            "intake_classified",
            engine=cls.engine,
            format=cls.format,
            tool=cls.tool,
            confidence=cls.format_confidence,
            ambiguous=list(cls.ambiguous),
            kickback=cls.kickback,
            kickback_code=cls.kickback_code,
            review_required=cls.review_required,
            validation_failures=cls.validation_failures,
            fallback_reason=cls.fallback_reason,
            decider_calls=cls.decider_calls,
            llm_calls=cls.llm_calls,
            model_latency_ms=cls.model_latency_ms,
            tokens=cls.tokens,
            before_extraction=cls.before_extraction,
            extractor_used=cls.extractor_used,
        )
        if cls.review_required:
            card.log(
                "intake_review_required",
                reason=cls.review_reason,
                validation_failures=cls.validation_failures,
                default=f"{cls.format} -> {cls.tool}",
            )
        if cls.kickback and cls.kickback_draft is not None:
            card.log(
                "kickback_drafted",
                code=cls.kickback_code,
                reason=cls.kickback_reason,
                to=cls.kickback_draft.to,
                chosen_by=cls.kickback_draft.chosen_by,
                status="awaiting_owner",
            )
        run.emit(
            "intake_classified",
            card_id=card.id,
            engine=cls.engine,
            format=cls.format,
            tool=cls.tool,
            kickback=cls.kickback,
            review_required=cls.review_required,
            validation_failures=cls.validation_failures,
            decisions=[{"key": d.key, "answer": d.answer, "engine": d.engine} for d in cls.decisions],
        )

    def _intake_one(self, card_id: str, sub: Submission) -> tuple[Invoice, list[str]]:
        notes: list[str] = []
        text = sub.text or ""
        fields: dict[str, Any] = {}
        origin: str = sub.amount_origin
        injections: list[str] = []
        if text:
            parsed = parse_invoice_text(text)
            fields = dict(parsed.fields)
            if self.llm.enabled:
                gate = GroundingIntervention(text)
                ext = self.llm.structured(
                    "intake",
                    INTAKE_PROMPT,
                    f"INVOICE TEXT:\n{text[:12000]}",
                    IntakeExtraction,
                    interventions=[gate],
                )
                if gate.guided:
                    fields_guided = sorted({f for entry in gate.log for f in entry["fields"]})
                    notes.append(
                        f"intake agent was guided back to the document {gate.guides}x "
                        f"(ungrounded: {', '.join(fields_guided)})"
                    )
                if ext is not None:
                    notes += self._merge_intake(ext, text, fields)
                    injections += ext.suspicious_instructions
                    if fields.get("_amount_origin") == "llm":
                        origin = "llm"
            missing = [
                f for f in ("vendor_name", "invoice_number", "amount_cents", "due_date") if f not in fields
            ]
            if missing:
                notes.append(f"could not read: {', '.join(missing)}")
        # Structured fields override text extraction (they come from the owner's own system).
        if sub.amount_cents is not None:
            fields["amount_cents"] = sub.amount_cents
        elif sub.amount:
            fields["amount_cents"] = parse_cents(sub.amount)
        for key in (
            "vendor_name",
            "invoice_number",
            "po_number",
            "bank_account",
            "remit_email",
            "issue_date",
            "due_date",
        ):
            if getattr(sub, key):
                fields[key] = getattr(sub, key)
        # Only an exact id from the owner's own system binds a vendor here; names, tax ids, domains and
        # bank accounts are resolved by the deterministic [resolve] node that follows.
        vendor = self.vendors.get(sub.vendor_id) if sub.vendor_id else None
        issue = fields.get("issue_date") or self.today
        due = fields.get("due_date")
        if due is None:
            due = issue + timedelta(days=30)
            notes.append("due date not found; kernel assumed net 30 from the issue date")
        amount = int(fields.get("amount_cents") or 0)
        if sub.amount_cents is None and not sub.amount and fields.get("_amount_origin") == "kernel":
            origin = "kernel"
        if amount <= 0:
            origin = "missing"
            notes.append("no verifiable amount; payment held until the amount is re-keyed from the source")
        inv = Invoice(
            id=card_id,
            vendor_id=vendor.id if vendor else sub.vendor_id,
            vendor_name=(vendor.name if vendor else None)
            or fields.get("vendor_name")
            or sub.vendor_name
            or "unknown vendor",
            invoice_number=str(fields.get("invoice_number") or f"UNNUMBERED-{card_id}"),
            amount_cents=abs(amount),
            currency=sub.currency,
            issue_date=issue,
            due_date=due,
            po_number=fields.get("po_number"),
            delivery_confirmed=sub.delivery_confirmed,
            bank_account=fields.get("bank_account"),
            remit_email=fields.get("remit_email"),
            line_items=sub.line_items,
            is_credit_note=sub.is_credit_note,
            submitted_by=sub.submitted_by,
            raw_text=text + ("\n" + "\n".join(injections) if injections else ""),
            source=sub.source or ("text" if text else "json"),
            amount_origin=origin,  # type: ignore[arg-type]
            discount_bps=sub.discount_bps,
            discount_days=sub.discount_days,
        )
        return inv, notes

    def _merge_intake(self, ext: IntakeExtraction, text: str, fields: dict[str, Any]) -> list[str]:
        """LLM quotes are only accepted if they are verbatim in the source; the kernel parses them."""
        notes = []
        if "amount_cents" in fields:
            if _quote_in_source(ext.amount_quote, text):
                try:
                    if parse_cents(ext.amount_quote) != fields["amount_cents"]:
                        notes.append(
                            f"intake disagreement: LLM pointed at {ext.amount_quote!r}; kernel kept the parsed total"
                        )
                except MoneyParseError:
                    pass
        elif ext.amount_quote:
            try:
                cents = parse_cents(ext.amount_quote)
            except MoneyParseError:
                cents = 0
            if _quote_in_source(ext.amount_quote, text) and cents > 0:
                fields["amount_cents"] = cents
                fields["_amount_origin"] = "kernel"
                notes.append("amount located by intake agent, verified verbatim in source, parsed by kernel")
            else:
                fields["amount_cents"] = cents
                fields["_amount_origin"] = "llm"
                notes.append("intake agent produced an amount that is not in the source document")
        for key, quote in (("due_date", ext.due_date_quote), ("issue_date", ext.issue_date_quote)):
            if key not in fields and quote and _quote_in_source(quote, text) and (d := parse_date(quote)):
                fields[key] = d
        if "bank_account" not in fields and ext.bank_account_quote:
            if _quote_in_source(ext.bank_account_quote, text):
                fields["bank_account"] = normalize_account(ext.bank_account_quote)
            else:
                notes.append(
                    "intake agent produced bank details that are not in the source document (ignored)"
                )
        for key in ("vendor_name", "invoice_number", "po_number", "remit_email"):
            value = getattr(ext, key)
            if key not in fields and value and _quote_in_source(value, text):
                fields[key] = value.strip()
        return notes

    # -- [kernel] ------------------------------------------------------------------------------------

    def kernel(self, run: Run) -> None:
        invoices = [c.invoice for c in run.card_list()]
        payable = allocate_credits(invoices)
        for card in run.card_list():
            inv = card.invoice
            vendor = self.vendors.get(inv.vendor_id or "")
            card.vendor = vendor.model_copy(deep=True) if vendor else None
            with card_step(card, "check"):
                shared = self.graph.shared(vendor.id) if vendor else {}
                checks = check_invoice(inv, vendor, invoices, self.limits, self.today, shared)
                card.checks = asdict(checks)
                card.flags = checks.flags()
                if inv.is_credit_note:
                    card.status = CardStatus.CREDIT
                    card.payable_cents = 0
                    card.log("credit_note", applied_cents=inv.amount_cents)
                    continue
                card.payable_cents = payable.get(inv.id, inv.amount_cents)
                if card.payable_cents != inv.amount_cents:
                    card.log("netted", credit_applied_cents=inv.amount_cents - card.payable_cents)
                card.features, card.categorical = invoice_features(inv, vendor, checks, self.graph)
            card.log("kernel_checked", flags=card.flags)
        totals = batch_totals(
            [(c.invoice.vendor_id or "?", c.invoice.currency, c.payable_cents) for c in self._payables(run)]
        )
        run.emit("kernel_done", totals=totals)

    def _payables(self, run: Run) -> list[PaymentCard]:
        return [c for c in run.card_list() if c.status != CardStatus.CREDIT]

    # -- [score] -------------------------------------------------------------------------------------

    def score(self, run: Run) -> None:
        cards = [c for c in self._payables(run) if c.features]
        if not cards:
            return
        items = [{"features": c.features, "categorical": c.categorical} for c in cards]
        t0 = time.perf_counter()
        scorer = self.scorer()
        try:
            results = scorer.score(items, explain=True)
        except Exception as exc:
            log.warning("scorer %s failed (%s); using heuristic fallback", getattr(scorer, "name", "?"), exc)
            results = HeuristicScorer().score(items, explain=True)
        self.time("scorer_ms", (time.perf_counter() - t0) * 1000)
        for card, res in zip(cards, results, strict=True):
            card.scores = res
            card.log("scored", scorer=res.scorer, top_class=res.top_class, legitimacy=res.legitimacy)
        run.emit("scored", scorer=results[0].scorer if results else None, n=len(cards))

    # -- facts ---------------------------------------------------------------------------------------

    def build_facts(self, card: PaymentCard) -> FactSheet:
        inv, v, ch = card.invoice, card.vendor, card.checks
        f = FactSheet()
        f.add("card_id", card.id)
        f.add("vendor_name", inv.vendor_name)
        f.add("invoice_number", inv.invoice_number)
        f.add_cents("invoice_amount", inv.amount_cents, inv.currency)
        f.add_cents("payable_amount", card.payable_cents, inv.currency)
        f.add("due_date", inv.due_date.isoformat())
        f.add("issue_date", inv.issue_date.isoformat())
        f.add("days_until_due", (inv.due_date - self.today).days)
        f.add("purchase_order", inv.po_number or "none")
        f.add("delivery_confirmed", "yes" if inv.delivery_confirmed else "no")
        f.add("bank_on_invoice", _mask(inv.bank_account))
        if v:
            f.add("vendor_id", v.id)
            f.add("bank_on_file", _mask(v.bank_account))
            f.add("phone_on_file", v.phone)
            f.add("vendor_country", v.country)
            f.add("vendor_age_days", v.created_days_ago)
            f.add("past_payments", len(v.history))
            if ch.get("history_median_cents"):
                f.add_cents("usual_amount", ch["history_median_cents"])
                f.add("amount_vs_usual", f"{ch['amount_ratio_milli'] / 1000:.1f}x")
            if v.bank_changed_days_ago is not None:
                f.add("bank_changed_days_ago", v.bank_changed_days_ago)
        if ch.get("split_total_cents"):
            f.add_cents("split_group_total", ch["split_total_cents"])
        if card.resolution:
            f.add("vendor_match", card.resolution.status)
            if card.resolution.matched_on:
                f.add("vendor_matched_on", ", ".join(card.resolution.matched_on))
        if card.sender and card.sender.checked:
            f.add("sender_email", card.sender.from_addr)
            f.add("sender_auth", "pass" if card.sender.auth_pass else "not verified")
            if card.sender.flags:
                f.add("sender_flags", ", ".join(card.sender.flags))
            if card.sender.lookalike and card.sender.lookalike.closest_known_domain:
                f.add("sender_lookalike_of", card.sender.lookalike.closest_known_domain)
        f.add_cents("approval_limit", self.limits.approval_limit_cents)
        f.add_cents("fast_pay_limit", self.limits.fast_pay_limit_cents)
        for i, flag in enumerate(card.flags, start=1):
            f.add(f"flag_{i}", flag)
        if card.scores:
            s = card.scores
            for cls, p in s.risk.items():
                f.add_percent(f"risk_{cls}", p)
            f.add_percent("legitimacy_confidence", s.legitimacy)
            f.add_percent("anomaly_percentile", s.anomaly)
            f.add("model", f"{s.scorer} {s.model_version}")
            for i, item in enumerate(s.lime[:3], start=1):
                f.add(f"top_factor_{i}", item["label"])
        if card.policy:
            f.add("decision", card.policy.lane.value)
            for i, r in enumerate(card.policy.reasons, start=1):
                f.add(f"reason_{i}", r)
            for i, a in enumerate(card.policy.required_actions, start=1):
                f.add(f"next_step_{i}", a)
        if card.funding and card.funding.get("pay_on"):
            f.add("pay_on", card.funding["pay_on"])
            if card.funding.get("discount_cents"):
                f.add_cents("early_pay_discount", card.funding["discount_cents"])
        f.add("status", card.status.value)
        card.facts = f.values
        return f

    # -- [investigate] -------------------------------------------------------------------------------

    def _investigator_for(self, card: PaymentCard) -> str | None:
        s, ch = card.scores, card.checks
        if s and max(s.risk.values()) >= 0.5:
            return max(s.risk, key=s.risk.get)
        if ch.get("bank_mismatch") or (ch.get("bank_change_recent") and not ch.get("bank_change_confirmed")):
            return "ato_bec"
        if card.sender and card.sender.suspicious:
            return "ato_bec"
        if card.resolution and card.resolution.status == "uncertain":
            return "fake_vendor"
        if ch.get("duplicate_of") or ch.get("split_group"):
            return "insider"
        if ch.get("shared_attributes") or not ch.get("vendor_found"):
            return "fake_vendor"
        if card.flags or (s and s.legitimacy < 0.5):
            return max(s.risk, key=s.risk.get) if s else "fake_vendor"
        return None

    def investigate(self, run: Run) -> None:
        from vouch.tools import get_tools

        budget = 8
        for card in self._payables(run):
            cls = self._investigator_for(card)
            if cls is None:
                continue
            facts = self.build_facts(card)
            template = self._template_investigation(card, cls)
            report = None
            if self.llm.enabled and budget > 0:
                budget -= 1
                with card_step(card, "investigate"):
                    report = self.llm.structured(
                        f"investigator:{cls}",
                        INVESTIGATOR_PROMPTS[cls],
                        f"FACTS:\n{facts.as_prompt()}",
                        InvestigationReport,
                        tools=get_tools(self),
                    )
            if report is None:
                card.investigation = template
            else:
                texts = [report.summary, *report.vendor_questions]
                prov = check_provenance(" ".join(texts), facts.values.values())
                if not prov.ok:
                    self.llm.stats.fallbacks += 1
                    card.log("provenance_rejected", role="investigator", unknown=prov.unknown)
                card.investigation = Investigation(
                    investigator=cls,
                    summary=report.summary if prov.ok else template.summary,
                    evidence=report.evidence[:8],
                    vendor_questions=report.vendor_questions[:4] if prov.ok else template.vendor_questions,
                    recommended_action=report.recommended_action,
                    source="llm" if prov.ok else "template",
                    provenance_ok=prov.ok,
                )
            card.log("investigated", investigator=cls, source=card.investigation.source)
            run.emit("investigated", card_id=card.id, investigator=cls, source=card.investigation.source)

    def _template_investigation(self, card: PaymentCard, cls: str) -> Investigation:
        v, ch = card.vendor, card.checks
        questions = {
            "ato_bec": [
                f"Call the vendor on {v.phone if v else 'a number you already have'} and ask: "
                "did you change your bank details?"
            ],
            "insider": ["Ask the vendor: is this a separate order? Get the PO and delivery note."],
            "fake_vendor": ["Ask the vendor for a W-9 and a bank letter on company letterhead."],
        }[cls]
        summary = "; ".join(card.flags) or "the risk score is higher than usual for this vendor"
        action = {
            "ato_bec": "verify_bank_by_callback",
            "insider": "confirm_not_duplicate" if ch.get("duplicate_of") else "request_po_and_delivery",
            "fake_vendor": "verify_identity",
        }[cls]
        return Investigation(
            investigator=cls,
            summary=summary[0].upper() + summary[1:] + ".",
            evidence=card.flags[:6],
            vendor_questions=questions,
            recommended_action=action,
            source="template",
        )

    # -- [policy] / [funding] ------------------------------------------------------------------------

    def decide(self, run: Run) -> None:
        for card in self._payables(run):
            if card.status in (CardStatus.PAID, CardStatus.APPROVED):
                continue
            with card_step(card, "policy"):
                outcome = evaluate_card(self.policy, card)
            changed = card.policy is None or card.policy.lane != outcome.lane
            card.policy = outcome
            card.status = CardStatus.HOLD if outcome.lane == Lane.HOLD else CardStatus.READY
            if changed:
                card.log("policy", lane=outcome.lane, reasons=outcome.reasons)
        lanes: dict[str, int] = {}
        for c in self._payables(run):
            if c.policy:
                lanes[c.policy.lane.value] = lanes.get(c.policy.lane.value, 0) + 1
        run.emit("policy_done", lanes=lanes)

    def fund(self, run: Run) -> None:
        cards = [c for c in self._payables(run) if c.status != CardStatus.PAID]
        for cid, rec in recommend(cards, self.forecast, self.today).items():
            run.cards[cid].funding = rec

    # -- [explain] -----------------------------------------------------------------------------------

    def template_explanation(self, card: PaymentCard) -> str:
        """One short plain sentence per card; the detail (reasons, next steps) lives on the card itself."""
        inv = card.invoice
        amount = format_cents(card.payable_cents, inv.currency)
        if card.status == CardStatus.CREDIT:
            return f"Credit note {inv.invoice_number} for {format_cents(inv.amount_cents)} applied to {inv.vendor_name}."
        if card.status == CardStatus.PAID:
            return f"Paid {amount} to {inv.vendor_name} for {inv.invoice_number}."
        p = card.policy
        if p is None:
            return f"Checking {inv.vendor_name} {inv.invoice_number} for {amount}."
        if p.lane == Lane.HOLD:
            step = p.required_actions[0] if p.required_actions else "owner review"
            why = " and ".join(p.reasons[:2])
            return f"Held: {why}. Next: {step}."
        when = card.funding.get("pay_on") if card.funding else None
        if p.lane == Lane.FAST_PAY:
            return (
                f"Fast pay: {inv.vendor_name} is a trusted vendor and {amount} is under your fast-pay limit."
            )
        return "Ready to pay: passed all checks" + (f", scheduled for {when}." if when else ".")

    def explain(self, run: Run) -> None:
        cards = run.card_list()
        for card in cards:
            self.build_facts(card)
        llm_cards = cards[:24] if self.llm.enabled else []
        written: dict[str, str] = {}
        for start in range(0, len(llm_cards), 8):
            chunk = llm_cards[start : start + 8]
            prompt = "\n\n".join(
                f"CARD {c.id}\nFACTS:\n" + "\n".join(f"- {k}: {v}" for k, v in sorted(c.facts.items()))
                for c in chunk
            )
            out = self.llm.structured("explainer", EXPLAINER_PROMPT, prompt, Explanations)
            if out:
                for item in out.items:
                    targets = [c.id for c in chunk] if item.card_id == "*" else [item.card_id]
                    written.update(dict.fromkeys(targets, item.text))
        for card in cards:
            text = written.get(card.id)
            if text:
                prov = check_provenance(text, card.facts.values())
                claims_paid = (
                    bool(re.search(r"\b(paid|approved|released|sent)\b", text, re.I))
                    and card.status != CardStatus.PAID
                )
                if prov.ok and not (claims_paid and card.status == CardStatus.HOLD):
                    card.explanation, card.explanation_source = text, "llm"
                    continue
                self.llm.stats.fallbacks += 1
                card.log(
                    "provenance_rejected", role="explainer", unknown=prov.unknown, claims_paid=claims_paid
                )
            card.explanation, card.explanation_source = self.template_explanation(card), "template"
        run.emit("explained", llm=sum(c.explanation_source == "llm" for c in cards), n=len(cards))

    # -- settlement ----------------------------------------------------------------------------------

    def _request(self, card: PaymentCard) -> PaymentRequest:
        v = card.vendor
        key = f"vouch:{card.invoice.vendor_id}:{_norm_invoice_number(card.invoice.invoice_number)}:{card.payable_cents}"
        return PaymentRequest(
            amount=Decimal(card.payable_cents) / 100,
            currency=card.invoice.currency,
            destination=f"vendor:{v.id}" if v else "unknown",
            memo=f"{card.invoice.invoice_number}",
            idempotency_key=key,
            metadata={"destination_tag": v.destination_tag if v else 0, "card_id": card.id},
        )

    def _pay(self, run: Run, cards: list[PaymentCard], lane: str) -> list[dict[str, Any]]:
        if not cards:
            return []
        t0 = time.perf_counter()
        try:
            receipts = self.adapter.send_batch([self._request(c) for c in cards], atomic=True)
        except Exception as exc:
            for c in cards:
                c.status = CardStatus.FAILED
                c.log("settlement_failed", error=str(exc))
            run.emit("settlement_failed", lane=lane, error=str(exc))
            return []
        settle_ms = (time.perf_counter() - t0) * 1000
        self.time("settlement_ms", settle_ms)
        out = []
        for card, rec in zip(cards, receipts, strict=True):
            ok = rec.status.value == "settled"
            card.step_ms["settle"] = round(settle_ms, 3)  # one batch transaction; same wall time per card
            card.receipt = {
                "tx_id": rec.tx_id,
                "status": rec.status.value,
                "network": rec.network,
                "explorer_url": rec.explorer_url,
                "amount": str(rec.amount),
                "currency": rec.currency,
                "batch_tx_id": rec.raw.get("batch_hash"),
                "batch_explorer_url": rec.raw.get("batch_explorer_url"),
                "idempotency_key": rec.idempotency_key,
            }
            card.status = CardStatus.PAID if ok else CardStatus.FAILED
            card.log("paid" if ok else "settlement_failed", tx_id=rec.tx_id, lane=lane)
            if ok and card.vendor and card.vendor.id in self.vendors:
                self.vendors[card.vendor.id].history.append(
                    PastPayment(
                        amount_cents=card.payable_cents,
                        days_ago=0,
                        invoice_number=card.invoice.invoice_number,
                    )
                )
            card.explanation, card.explanation_source = self.template_explanation(card), "template"
            card.facts = self.build_facts(card).values
            out.append({"card_id": card.id, **card.receipt})
        settlement = {
            "at": now_iso(),
            "lane": lane,
            "adapter": self.adapter.name,
            "network": self.adapter.network,
            "total_cents": sum(c.payable_cents for c in cards),
            "payments": out,
        }
        run.settlements.append(settlement)
        run.emit(
            "settled",
            lane=lane,
            n=len(out),
            total_cents=settlement["total_cents"],
            tx_ids=[p["tx_id"] for p in out],
        )
        return out

    def fast_pay(self, run: Run) -> None:
        cards = [
            c
            for c in self._payables(run)
            if c.status == CardStatus.READY
            and c.policy
            and c.policy.lane == Lane.FAST_PAY
            and c.funding
            and c.funding.get("action") == "pay_now"
        ]
        cards = [c for c in cards if evaluate_card(self.policy, c).lane == Lane.FAST_PAY]
        if not cards:
            return
        decision = evaluate_batch(self.policy, cards, owner_approved=False, fast_pay_only=True)
        if not decision.allowed:
            run.emit("batch_blocked", lane="fast_pay", reasons=decision.reasons)
            return
        self._pay(run, cards, "fast_pay")

    def approval_summary(self, run: Run) -> dict[str, Any] | None:
        ready = [c for c in self._payables(run) if c.status in (CardStatus.READY, CardStatus.APPROVED)]
        if not ready:
            return None
        holds = [c for c in self._payables(run) if c.status == CardStatus.HOLD]
        return {
            "message": f"Approve paying {len(ready)} vendor(s) {format_cents(sum(c.payable_cents for c in ready))} "
            f"via {self.adapter.name}? {len(holds)} card(s) stay on hold.",
            "cards": [
                {
                    "card_id": c.id,
                    "vendor": c.invoice.vendor_name,
                    "payable_cents": c.payable_cents,
                    "lane": c.policy.lane.value if c.policy else None,
                    "pay_on": (c.funding or {}).get("pay_on"),
                }
                for c in ready
            ],
            "total_cents": sum(c.payable_cents for c in ready),
            "on_hold": [c.id for c in holds],
            "adapter": self.adapter.name,
        }

    def settle(self, run: Run) -> None:
        approval = run.approval or {}
        if not approval.get("approved"):
            run.emit("settle_skipped", reason=approval.get("reason") or "owner did not approve")
            return
        wanted = approval.get("card_ids")
        selected, blocked = [], []
        for card in self._payables(run):
            if card.status == CardStatus.PAID:
                continue
            if wanted is not None and card.id not in wanted:
                continue
            if wanted is None and card.status not in (CardStatus.READY, CardStatus.APPROVED):
                continue
            outcome = evaluate_card(self.policy, card)  # re-check at the moment money moves
            if outcome.allowed:
                selected.append(card)
            else:
                blocked.append({"card_id": card.id, "reasons": outcome.reasons})
                card.log("settle_blocked_by_policy", reasons=outcome.reasons)
        if blocked:
            run.emit("settle_blocked", cards=blocked)
        if not selected:
            return
        decision = evaluate_batch(self.policy, selected, owner_approved=True)
        if not decision.allowed:
            run.emit("batch_blocked", lane="standard", reasons=decision.reasons)
            for c in selected:
                c.log("batch_blocked", reasons=decision.reasons)
            return
        for c in selected:
            c.resolutions.append(
                Resolution(
                    kind="approve",
                    actor=approval.get("approver", "owner"),
                    at=now_iso(),
                    note=approval.get("note", ""),
                )
            )
        self._pay(run, selected, "standard")

    # -- owner actions -------------------------------------------------------------------------------

    def resolve(self, card_id: str, resolution: Resolution, phone_called: str | None = None) -> PaymentCard:
        run, card = self.find_card(card_id)
        if card.status == CardStatus.PAID:
            raise ValidationFailedError("card is already paid")
        if resolution.kind == "confirm_bank":
            on_file = card.vendor.phone if card.vendor else None
            digits = lambda s: re.sub(r"\D", "", s or "")  # noqa: E731
            if not on_file or digits(phone_called) != digits(on_file):
                raise ValidationFailedError(
                    "bank changes must be confirmed by calling the phone number already on file",
                    details={"phone_on_file": on_file},
                )
            resolution.method = resolution.method or f"call-back to {on_file} (on file)"
        resolution.at = resolution.at or now_iso()
        card.resolutions.append(resolution)
        card.log("resolution", kind=resolution.kind, actor=resolution.actor, note=resolution.note)
        run.emit("resolution", card_id=card.id, resolution=resolution.kind)
        if resolution.kind == "appeal":
            card.log("appeal_queued", note="vendor appeal recorded; owner review prioritised")
        self.decide(run)
        self.fund(run)
        card.explanation, card.explanation_source = self.template_explanation(card), "template"
        self.build_facts(card)
        self.changed(run)
        return card
