"""VouchService: the façade the API, the demo CLI and the tests share.

It owns the engine (vendor master, runs, Strands graph), the audit store (Postgres or SQLite), the
attachment store (Object Storage or disk), the embedding index (pgvector or memory) and the LLM
runtime, and it translates between the frontend's payment contract (approve / hold / appeal / batch
settle) and the engine's cards, lanes and owner resolutions.

Money only moves through `pipeline.approve` -> engine.settle -> settlement adapter, so every path
(single approve, batch, fast-pay) passes the same approval interrupt, policy re-check and adapter;
with ``SETTLEMENT_ADAPTER=xrpl`` the receipts carry real XRPL testnet transaction hashes.
"""

from __future__ import annotations

import base64
import itertools
import logging
import secrets
import threading
from datetime import UTC, date, datetime, timedelta
from typing import Any

from hm_core.errors import ForbiddenError, NotFoundError, UpstreamError, ValidationFailedError
from hm_settlement import SettlementAdapter
from vouch import __version__
from vouch.audit import AuditStore
from vouch.cards import PaymentCard, now_iso
from vouch.config import Settings, get_settings
from vouch.contracts import ExtractedDocument, IntakeRequest, iso, utcnow
from vouch.decider import KINDS_FOR_TOOL, IntakeClassification, extractor_for, probes_from_files
from vouch.domain import CardStatus, Lane, Resolution
from vouch.engine import Run, Submission, VouchEngine
from vouch.intake import combine_documents, envelope_from_headers, extract_file, intake_body_text, parse_eml
from vouch.intake.extract import detect_kind
from vouch.llm import LLMRuntime
from vouch.mail import Mailer, OutboxMailer
from vouch.policy import PaymentAttrs, authorize, cedar_available
from vouch.scorer import Scorer
from vouch.storage import AttachmentStore
from vouch.vendors import VendorDirectory, index_vendors, make_embedding_index
from vouch.views import lifecycle_of, payment_view, receipt_view, risk_of, trust_score, vouch_status

log = logging.getLogger(__name__)


class VouchService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        engine: VouchEngine | None = None,
        store: AuditStore | None = None,
        database_url: str | None = None,
        llm_mode: str | None = None,
        adapter: SettlementAdapter | None = None,
        scorer: Scorer | None = None,
        today: date | None = None,
        seed_demo: bool | None = None,
        restore: bool = True,
        mailer: Mailer | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        s = self.settings
        url = database_url or s.effective_database_url
        self.store = store or AuditStore.open(url, s.sqlite_url)
        self.attachments = AttachmentStore(s)
        self.mailer: Mailer = mailer or OutboxMailer()
        self.lock = threading.RLock()
        self.started_at = utcnow()
        self.vendors_indexed = 0
        self.redteam: dict[str, Any] | None = None
        self._decision_sig: dict[str, tuple[Any, ...]] = {}

        if engine is None:
            if llm_mode and llm_mode != "auto":
                s = s.model_copy(update={"llm_mode": llm_mode})
            llm = LLMRuntime.from_settings(
                s,
                embedding_lookup=self.store.embedding_lookup,
                embedding_persist=self.store.embedding_persist,
            )
            engine = VouchEngine(settings=s, llm=llm, adapter=adapter, scorer=scorer, today=today)
        self.engine = engine
        self.engine.embedding_index = make_embedding_index(
            self.store.engine, self.store.backend == "postgres"
        )

        if restore:
            self._restore()
        self.engine.on_change = self._persist_run
        self.engine.on_vendors_changed = self.store.save_vendors
        if self.engine.vendors and self.store.counts()["vendors"] == 0:
            self.store.save_vendors(list(self.engine.vendors.values()))

        want_seed = s.seed_demo if seed_demo is None else seed_demo
        if want_seed and not self.engine.runs:
            self.seed(run_demo=True)
        self.index_vendor_embeddings()

    # -- persistence -------------------------------------------------------------------------------

    def _persist_run(self, run: Run) -> None:
        self.store.save_run(run, llm_mode=self.engine.llm.mode, model=self.engine.llm.model_name)
        for card in run.card_list():
            if card.policy is None:
                continue
            sig = (card.policy.lane.value, card.status.value, tuple(card.policy.reasons))
            if self._decision_sig.get(card.id) != sig:
                self._decision_sig[card.id] = sig
                self.store.record_decision(card)
            if card.intake is not None:
                self.store.record_intake_decisions(card)
                self.store.save_kickback_draft(card)
        paid_vendors = {c.invoice.vendor_id for c in run.card_list() if c.status == CardStatus.PAID}
        touched = [self.engine.vendors[v] for v in paid_vendors if v in self.engine.vendors]
        if touched:
            self.store.save_vendors(touched)

    def _restore(self) -> None:
        vendors = self.store.load_vendors()
        if vendors and not self.engine.vendors:
            self.engine.load_vendors(vendors, replace=True)
        restored = 0
        for data in self.store.load_runs():
            if data["id"] in self.engine.runs:
                continue
            run = Run(
                id=data["id"],
                submissions=[Submission.model_validate(sub) for sub in data.get("submissions", [])],
                created_at=data.get("created_at") or now_iso(),
                status=data.get("status") or "completed",
                label=data.get("label") or "",
                cards={c.id: c for c in data.get("cards", [])},
                events=list(data.get("events") or []),
                node_ms=dict(data.get("node_ms") or {}),
                pending=data.get("pending"),
                approval=data.get("approval"),
                settlements=list(data.get("settlements") or []),
                error=data.get("error"),
            )
            if run.status == "running":
                run.status, run.error = "failed", "interrupted by a restart"
                run.emit("run_failed", error=run.error)
            # The Strands graph object is not persisted: the next approval builds a fresh settle graph
            # (policy -> funding -> settle) that re-checks every card before money moves.
            run.graph = None
            self.engine.runs[run.id] = run
            for card in run.card_list():
                if card.policy:
                    self._decision_sig[card.id] = (
                        card.policy.lane.value,
                        card.status.value,
                        tuple(card.policy.reasons),
                    )
            restored += 1
        if restored:
            log.info("restored %d run(s) from %s", restored, self.store.backend)

    # -- demo / admin ------------------------------------------------------------------------------

    def seed(self, run_demo: bool = True, background_vendors: int = 250) -> Run | None:
        from vouch.demo import demo_submissions, seed
        from vouch.pipeline import execute

        with self.lock:
            seed(self.engine, background_vendors=background_vendors)
            if not run_demo:
                return None
            run = self.engine.new_run(demo_submissions(self.engine.today), label="demo: Friday vendor run")
            execute(self.engine, run)
            return run

    def reset(self, run_demo: bool = True) -> Run | None:
        """Forget every run (audit rows stay) and optionally replay the scripted demo."""
        with self.lock:
            self.engine.runs.clear()
            self._decision_sig.clear()
            self.store.delete_all_runs()
            self.redteam = None
            return self.seed(run_demo=run_demo)

    def index_vendor_embeddings(self, limit: int = 64) -> int:
        embedder = self.engine.llm.embedder_or_none()
        if embedder is None or self.engine.embedding_index is None:
            return 0
        vendors = list(self.engine.vendors.values())
        demo = [v for v in vendors if v.id.startswith("v-")]
        rest = [v for v in vendors if not v.id.startswith("v-")][: max(0, limit - len(demo))]
        try:
            self.vendors_indexed = index_vendors(
                VendorDirectory(demo + rest), embedder, self.engine.embedding_index
            )
        except Exception as exc:  # embeddings are a re-ranker only; never block startup on them
            log.warning("vendor embedding index skipped: %s", exc)
        return self.vendors_indexed

    def uptime_s(self) -> int:
        return int((utcnow() - self.started_at).total_seconds())

    # -- intake ------------------------------------------------------------------------------------

    def submit(self, submissions: list[Submission], label: str = "") -> Run:
        from vouch.pipeline import execute

        with self.lock:
            run = self.engine.new_run(submissions, label=label)
            execute(self.engine, run)
            return run

    def intake(self, request: IntakeRequest, label: str = "") -> Run:
        """One email or upload -> one invoice -> one run through the full graph.

        The decision chain runs *before* extraction: cheap probes (MIME type, extension, magic bytes, PDF
        text layer; no OCR) -> ``IntakeClassifier.classify`` (deterministic first; the Decider or the chat
        classifier only when the route is ambiguous) -> the tool decision picks the extractor
        (``extractor_for``). A tool that does not read a file, raises, or is ``request_resubmission`` falls
        back to the default extractor, so the record always has the hash and whatever text there is. Which
        tool was decided, which extractor ran and why is recorded per document (card timeline, run,
        ``intake_documents``); the engine completes the chain once the kernel has parsed the text.
        """
        intake_id = f"in-{secrets.token_hex(4)}"
        body = intake_body_text(request)
        source = "email" if request.source == "email" else "upload"
        files = [(att, base64.b64decode(att.data_b64)) for att in request.attachments if att.data_b64]
        files = [(att, data) for att, data in files if data]
        routing = self._route_intake(
            [(att.filename, att.content_type, data) for att, data in files], body, request.headers, source
        )
        tool = routing.tool if routing is not None else None
        docs: list[ExtractedDocument] = []
        records: list[dict[str, Any]] = []
        stored: list[tuple[ExtractedDocument, str | None, dict[str, Any]]] = []
        if body.strip():
            doc = ExtractedDocument(
                filename="email-body", kind="email_body", text=body, extractor="email-body"
            )
            docs.append(doc)
            records.append(_document_record(doc))
        for att, data in files:
            doc, choice = self._extract_routed(data, att.filename, att.content_type, tool)
            key = None
            try:
                key = self.attachments.put(
                    AttachmentStore.key_for(intake_id, doc.sha256 or att.sha256, att.filename),
                    data,
                    att.content_type,
                )
            except Exception as exc:  # storage is best effort; the hash is what the audit trail needs
                log.warning("attachment not stored: %s", exc)
            docs.append(doc)
            records.append({**_document_record(doc), **choice})
            stored.append((doc, key, choice))
        text = combine_documents(docs).strip()
        if not text:
            raise ValidationFailedError(
                "no readable text in the email body or attachments",
                details={"documents": [d.model_dump(exclude={"text", "tables"}) for d in docs]},
            )
        sub = Submission(
            text=text,
            headers=dict(request.headers),
            source=source,
            received_at=iso(request.received_at) if request.received_at else now_iso(),
            documents=records,
            routing=routing.model_dump(mode="json") if routing is not None else None,
            submitted_by=request.submitted_by,
            delivery_confirmed=request.delivery_confirmed,
            po_number=request.po_number,
        )
        run = self.submit([sub], label=label or f"{request.source} intake")
        card_id = f"{run.id}.1"
        for doc, key, choice in stored:
            self.store.record_document(
                run.id,
                card_id,
                doc.filename,
                doc.kind,
                doc.sha256,
                doc.extractor,
                doc.text,
                key,
                tool=choice.get("tool"),
                fallback=choice.get("fallback"),
            )
        return run

    def _route_intake(
        self,
        files: list[tuple[str, str | None, bytes]],
        body: str,
        headers: dict[str, str],
        source: str,
    ) -> IntakeClassification | None:
        """The decision chain over pre-extraction probes. Advisory: if it fails, extraction uses the default
        extractors and the engine classifies after the fact, as it does for text-only submissions."""
        if not files and not body.strip():
            return None
        try:
            probes = probes_from_files(files, body_text=body)
            envelope = envelope_from_headers(dict(headers)) if headers else None
            cls = self.engine.classifier.classify(probes, envelope, source=source)
        except Exception as exc:
            log.warning("intake routing before extraction failed: %s", exc)
            return None
        cls.before_extraction = True
        cls.notes.append("decided before extraction; the tool decision chose the extractor")
        return cls

    @staticmethod
    def _extract_routed(
        data: bytes, filename: str, content_type: str | None, tool: str | None
    ) -> tuple[ExtractedDocument, dict[str, Any]]:
        """Extract one attachment with the extractor the tool decision maps to, or the default one.

        Returns the document and the record for the audit trail: ``tool`` (the chain's decision) and
        ``fallback`` (``None`` when that tool's extractor ran on this file, otherwise why the default ran).
        """
        kind = detect_kind(filename, content_type, data)
        choice: dict[str, Any] = {"tool": tool, "fallback": None}
        serves = KINDS_FOR_TOOL.get(tool or "", ())
        fn = extractor_for(tool, kind) if tool and kind in serves else None
        if fn is None:
            if tool is None:
                choice["fallback"] = "no routing decision; default extractor"
            elif tool == "request_resubmission":
                choice["fallback"] = (
                    "request_resubmission: default extractor keeps the hash and any text for the record"
                )
            else:
                choice["fallback"] = (
                    f"default extractor: {tool} reads {', '.join(serves) or 'no'} files, this one is {kind}"
                )
            return extract_file(data, filename, content_type), choice
        try:
            return fn(data, filename), choice
        except Exception as exc:  # the chosen extractor must never lose the document
            log.warning("%s failed on %s (%s); default extractor used", tool, filename, exc)
            choice["fallback"] = f"{tool} failed ({type(exc).__name__}); default extractor"
            return extract_file(data, filename, content_type), choice

    def intake_eml(self, raw: bytes, *, submitted_by: str = "ap-inbox") -> Run:
        req = parse_eml(raw)
        req.submitted_by = submitted_by
        return self.intake(req, label="email intake")

    def intake_files(
        self,
        files: list[tuple[str, str | None, bytes]],
        *,
        submitted_by: str = "ap-clerk",
        delivery_confirmed: bool = False,
        po_number: str | None = None,
        body_text: str = "",
    ) -> Run:
        from vouch.contracts import Attachment

        req = IntakeRequest(
            source="upload",
            body_text=body_text,
            submitted_by=submitted_by,
            delivery_confirmed=delivery_confirmed,
            po_number=po_number,
            attachments=[
                Attachment(
                    filename=name,
                    content_type=ctype or "application/octet-stream",
                    data_b64=base64.b64encode(data).decode(),
                    size=len(data),
                )
                for name, ctype, data in files
            ],
        )
        return self.intake(req, label="file upload")

    # -- payments (frontend contract) --------------------------------------------------------------

    def _pairs(self) -> list[tuple[Run, PaymentCard]]:
        return [(run, card) for run in self.engine.runs.values() for card in run.card_list()]

    def payments(self) -> list[dict[str, Any]]:
        return [payment_view(self.engine, run, card) for run, card in self._pairs()]

    def payment(self, card_id: str) -> dict[str, Any]:
        run, card = self.engine.find_card(card_id)
        return payment_view(self.engine, run, card)

    def find(self, card_id: str) -> tuple[Run, PaymentCard]:
        return self.engine.find_card(card_id)

    def _attrs(self, card: PaymentCard) -> PaymentAttrs:
        ch = card.checks
        return PaymentAttrs(
            status=vouch_status(card),
            lifecycle=lifecycle_of(card),
            risk=risk_of(card),
            trust_score=trust_score(card),
            fast_pay_eligible=bool(card.policy and card.policy.lane == Lane.FAST_PAY),
            bank_changed=bool(ch.get("bank_mismatch") or ch.get("bank_change_recent")),
            bank_change_verified=bool(ch.get("bank_change_confirmed") or card.has_resolution("confirm_bank")),
            amount_cents=card.payable_cents,
            vendor_known=card.vendor is not None,
        )

    def _authorize(
        self, card: PaymentCard, principal: str, action: str, context: dict[str, Any] | None = None
    ) -> list[str]:
        outcome = authorize(principal, action, self._attrs(card), context, payment_id=card.id)
        self.store.record_policy(
            card.run_id, card.id, outcome.engine, principal.lower(), action, outcome.allowed, outcome.reasons
        )
        if not outcome.allowed:
            raise ForbiddenError(
                f"{action} denied by policy ({outcome.engine}): {', '.join(outcome.reasons)}",
                details={
                    "rules": outcome.reasons,
                    "lifecycle": lifecycle_of(card),
                    "status": vouch_status(card),
                },
            )
        return outcome.reasons

    def _resolve(self, card: PaymentCard, kind: str, actor: str, note: str, **kw: Any) -> PaymentCard:
        return self.engine.resolve(card.id, Resolution(kind=kind, actor=actor, note=note), **kw)  # type: ignore[arg-type]

    def _clear_holds(self, card: PaymentCard, actor: str, note: str) -> None:
        """Owner verification from the console: release the owner hold, resolve reviewable risks, and
        record the call-back confirmation for bank holds (the console only ever shows the number on file)."""
        if card.policy is None or card.policy.lane != Lane.HOLD:
            return
        reasons = set(card.policy.reasons)
        from vouch.policy import R_BANK, R_LIMIT, R_OWNER_HOLD

        if R_OWNER_HOLD in reasons:
            self._resolve(card, "release_hold", actor, note)
        if R_BANK in reasons and card.vendor:
            self._resolve(
                card,
                "confirm_bank",
                actor,
                note or "call-back checklist completed in the Vouch console",
                phone_called=card.vendor.phone,
            )
        if R_LIMIT in reasons:
            self._resolve(card, "limit_override", actor, note or "one-time limit override by the owner")
        if not card.has_resolution("resolve_risk"):
            self._resolve(
                card, "resolve_risk", actor, note or "owner reviewed the evidence and verified the payment"
            )

    def approve(self, card_id: str, note: str | None = None, author: str = "Owner") -> dict[str, Any]:
        """Owner approval: a READY card becomes APPROVED (in the batch); a HOLD card is first verified."""
        with self.lock:
            run, card = self.engine.find_card(card_id)
            if card.status in (CardStatus.PAID, CardStatus.APPROVED):
                return payment_view(self.engine, run, card)
            text = (note or "").strip()
            rules = self._authorize(card, "Owner", "approve")
            if card.status == CardStatus.HOLD:
                self._clear_holds(card, author, text)
                if card.status == CardStatus.HOLD:
                    raise ValidationFailedError(
                        "still on hold: " + "; ".join(card.policy.reasons if card.policy else []),
                        details={"required_actions": card.policy.required_actions if card.policy else []},
                    )
            card.resolutions.append(
                Resolution(kind="approve", actor=author, note=text or "Approved by the owner", at=now_iso())
            )
            card.status = CardStatus.APPROVED
            card.log("owner_approved", actor=author, note=text)
            run.emit("owner_approved", card_id=card.id, actor=author)
            card.explanation, card.explanation_source = self.engine.template_explanation(card), "template"
            self.engine.build_facts(card)
            self.store.record_approval(card.id, "approve", text, author, rules[0] if rules else None)
            self.engine.changed(run)
            return payment_view(self.engine, run, card)

    def hold(self, card_id: str, note: str | None = None, author: str = "Owner") -> dict[str, Any]:
        with self.lock:
            run, card = self.engine.find_card(card_id)
            text = (note or "").strip() or "Held for a quick check"
            rules = self._authorize(card, "Owner", "hold")
            if card.status == CardStatus.APPROVED:
                card.status = CardStatus.READY  # back out of the batch first
            self._resolve(card, "owner_hold", author, text)
            self.store.record_approval(card.id, "hold", text, author, rules[0] if rules else None)
            return payment_view(self.engine, run, card)

    def appeal(self, card_id: str, note: str | None = None, author: str = "Owner") -> dict[str, Any]:
        """'Vendor is fine': the owner vouches, reviewable holds are resolved, the card waits in the batch."""
        with self.lock:
            run, card = self.engine.find_card(card_id)
            text = (note or "").strip() or "Owner vouched for this vendor"
            rules = self._authorize(card, "Owner", "appeal")
            if card.status == CardStatus.HOLD:
                self._clear_holds(card, author, text)
            self._resolve(card, "appeal", author, text)
            self.store.record_approval(card.id, "appeal", text, author, rules[0] if rules else None)
            return payment_view(self.engine, run, card)

    # -- kickback outbox (drafts to senders; the owner decides, nothing sends) ----------------------

    def kickback_decide(
        self, card_id: str, approve: bool, note: str | None = None, author: str = "Owner"
    ) -> dict[str, Any]:
        """The owner approves (clears for sending by a mail integration) or declines a kickback draft.

        Cedar P-08: only an Owner may do this; System and Model are denied, so nothing can approve a
        reply to a sender automatically. The payment stays on hold either way: approving the email does
        not make the invoice payable - a readable resubmission or the owner re-keying it does.
        """
        with self.lock:
            run, card = self.engine.find_card(card_id)
            draft = card.intake.kickback_draft if card.intake else None
            if draft is None:
                raise NotFoundError(f"no kickback draft for {card_id}")
            action = "approve_kickback" if approve else "decline_kickback"
            text = (note or "").strip()
            rules = self._authorize(card, "Owner", action)
            if draft.status == "awaiting_owner":
                draft.status = "approved" if approve else "declined"
                draft.decided_by, draft.decided_at, draft.note = author, now_iso(), text
                card.log(
                    "kickback_approved" if approve else "kickback_declined",
                    actor=author,
                    note=text,
                    to=draft.to,
                    code=draft.code,
                )
                run.emit("kickback_decided", card_id=card.id, status=draft.status, actor=author)
                self.store.record_approval(card.id, action, text, author, rules[0] if rules else None)
                self.store.save_kickback_draft(card)
                self.engine.changed(run)
            return payment_view(self.engine, run, card)

    def kickback_send(self, card_id: str, note: str | None = None, author: str = "Owner") -> dict[str, Any]:
        """The owner hands an approved kickback draft to the mail integration.

        Cedar P-09 is the only gate between a draft and the ``Mailer``: Owner principal, the owner's P-08
        approval on record (``kickback_approved``), not sent before (``kickback_sent``), payment not
        settled. System and Model have no permit, so a draft that is awaiting the owner, declined or
        already sent is a 403 and the mailer is never called. Sending changes nothing about the payment:
        it stays on hold until a readable invoice arrives or the owner re-keys it.
        """
        with self.lock:
            run, card = self.engine.find_card(card_id)
            draft = card.intake.kickback_draft if card.intake else None
            if draft is None:
                raise NotFoundError(f"no kickback draft for {card_id}")
            text = (note or "").strip()
            rules = self._authorize(
                card,
                "Owner",
                "send_kickback",
                {
                    "kickback_approved": draft.status in ("approved", "sent"),
                    "kickback_sent": draft.sent_at is not None,
                },
            )
            message_id = self.mailer.send(draft.to, draft.subject, draft.body)
            draft.status = "sent"
            draft.sent_at, draft.sent_by, draft.sent_via, draft.message_id = (
                now_iso(),
                author,
                self.mailer.name,
                message_id,
            )
            card.log(
                "kickback_sent",
                actor=author,
                note=text,
                to=draft.to,
                code=draft.code,
                via=self.mailer.name,
                message_id=message_id,
            )
            run.emit("kickback_sent", card_id=card.id, actor=author, via=self.mailer.name)
            self.store.record_approval(card.id, "send_kickback", text, author, rules[0] if rules else None)
            self.store.save_kickback_draft(card)
            self.engine.changed(run)
            return payment_view(self.engine, run, card)

    def outbox(self, status: str | None = None) -> list[dict[str, Any]]:
        """Kickback drafts, newest first (``status`` filters: awaiting_owner | approved | declined | sent)."""
        items = []
        for run, card in self._pairs():
            draft = card.intake.kickback_draft if card.intake else None
            if draft is None or (status and draft.status != status):
                continue
            items.append(
                {
                    "payment_id": card.id,
                    "run_id": run.id,
                    "vendor": card.invoice.vendor_name,
                    "received_at": run.created_at,
                    **draft.model_dump(),
                }
            )
        items.sort(key=lambda d: d["received_at"], reverse=True)
        return items

    def settle(
        self, card_ids: list[str], funding: str = "now", author: str = "Owner", note: str = ""
    ) -> dict[str, Any]:
        """Batch settlement for the frontend: every card is owner-approved, Cedar-checked and then paid
        by the engine's settle node (policy re-check -> adapter batch). Real XRPL hashes with the xrpl adapter."""
        from vouch.pipeline import approve as approve_run

        with self.lock:
            pairs = [self.engine.find_card(cid) for cid in dict.fromkeys(card_ids)]
            for _run, card in pairs:
                if card.status == CardStatus.PAID:
                    raise ValidationFailedError(f"{card.id} is already settled", details={"tx": card.receipt})
                if card.status == CardStatus.HOLD:
                    raise ValidationFailedError(
                        f"{card.id} is on hold: " + "; ".join(card.policy.reasons if card.policy else []),
                        details={
                            "card_id": card.id,
                            "required_actions": card.policy.required_actions if card.policy else [],
                        },
                    )
                if card.status != CardStatus.APPROVED:
                    self.approve(card.id, note or "Approved in batch", author)
                self._authorize(card, "System", "settle", {"owner_approval_recorded": True})
            batch_id = f"batch-{secrets.token_hex(3)}"
            adapter = self.engine.adapter
            if funding == "scheduled":
                pay_on = self._next_business_day()
                for run, card in pairs:
                    card.funding = {
                        **(card.funding or {}),
                        "action": "schedule",
                        "pay_on": pay_on.isoformat(),
                        "reason": "owner scheduled the batch",
                    }
                    card.log("scheduled", pay_on=pay_on.isoformat(), batch_id=batch_id)
                    self.engine.changed(run)
                scheduled_for = f"{pay_on.isoformat()}T14:00:00Z"
                self.store.record_settlement(
                    batch_id, pairs[0][0].id, "", None, [c.id for _, c in pairs],
                    sum(c.payable_cents for _, c in pairs), funding, scheduled_for,
                    adapter.name, adapter.network, "scheduled", [],
                )  # fmt: skip
                return receipt_view(
                    batch_id=batch_id, settlements=[], cards=pairs, funding=funding,
                    scheduled_for=scheduled_for, adapter_name=adapter.name, network=adapter.network,
                    public_url=self.settings.public_url,
                )  # fmt: skip

            by_run: dict[str, list[str]] = {}
            runs: dict[str, Run] = {}
            for run, card in pairs:
                by_run.setdefault(run.id, []).append(card.id)
                runs[run.id] = run
            before = {rid: len(runs[rid].settlements) for rid in by_run}
            errors: list[str] = []
            for rid, ids in by_run.items():
                try:
                    approve_run(
                        self.engine,
                        runs[rid],
                        {"approved": True, "card_ids": ids, "approver": author, "note": note},
                    )
                except Exception as exc:  # the run records the failure; report it with the receipt
                    log.exception("settlement failed for run %s", rid)
                    errors.append(f"{rid}: {exc}")
            settlements = [s for rid, run in runs.items() for s in run.settlements[before[rid] :]]
            paid = [c for _, c in pairs if c.status == CardStatus.PAID]
            if not paid:
                detail = errors or [
                    e.get("error") or str(e.get("reasons") or e.get("cards"))
                    for run in runs.values()
                    for e in run.events[-6:]
                    if e["type"] in ("settlement_failed", "batch_blocked", "settle_blocked")
                ]
                raise UpstreamError(
                    "settlement did not complete: " + "; ".join(detail or ["no card was paid"])
                )
            payments = [p for s in settlements for p in s.get("payments", [])]
            first = payments[0] if payments else {}
            self.store.record_settlement(
                batch_id, pairs[0][0].id,
                first.get("batch_tx_id") or first.get("tx_id") or "",
                first.get("batch_explorer_url") or first.get("explorer_url"),
                [c.id for c in paid], sum(c.payable_cents for c in paid), funding, None,
                adapter.name, adapter.network, "standard", payments,
            )  # fmt: skip
            receipt = receipt_view(
                batch_id=batch_id, settlements=settlements, cards=pairs, funding=funding,
                scheduled_for=None, adapter_name=adapter.name, network=adapter.network,
                public_url=self.settings.public_url,
            )  # fmt: skip
            if errors:
                receipt["errors"] = errors
            return receipt

    def _next_business_day(self) -> date:
        d = self.engine.today + timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d

    def receipt(self, tx_id: str) -> dict[str, Any]:
        """Settlement record for one transaction id (the 'explorer' for the mock ledger)."""
        for run in self.engine.runs.values():
            for card in run.card_list():
                rec = card.receipt or {}
                if tx_id in (rec.get("tx_id"), rec.get("batch_tx_id")):
                    return {
                        "tx_id": tx_id,
                        "card_id": card.id,
                        "run_id": run.id,
                        "vendor": card.invoice.vendor_name,
                        "invoice_number": card.invoice.invoice_number,
                        "amount_cents": card.payable_cents,
                        "receipt": rec,
                        "settlements": [
                            s
                            for s in run.settlements
                            if any(
                                p.get("tx_id") == tx_id or p.get("batch_tx_id") == tx_id
                                for p in s.get("payments", [])
                            )
                        ],
                        "stored": [
                            s
                            for s in self.store.settlements(200)
                            if s["tx_id"] == tx_id or card.id in (s.get("card_ids") or [])
                        ],
                    }
        raise NotFoundError(f"unknown transaction {tx_id}")

    def audit(self, card_id: str) -> dict[str, Any]:
        run, card = self.engine.find_card(card_id)
        return {
            "card_id": card.id,
            "run_id": run.id,
            "status": card.status.value,
            "lane": card.policy.lane.value if card.policy else None,
            "timeline": card.timeline,
            "resolutions": [r.model_dump() for r in card.resolutions],
            "receipt": card.receipt,
            "store": self.store.audit_trail(card.id),
        }

    # -- vitals ------------------------------------------------------------------------------------

    def info(self) -> dict[str, Any]:
        e = self.engine
        s = self.settings
        scorer = e.scorer()
        return {
            "project": "vouch",
            "app": s.app_name,
            "version": __version__,
            "description": "Payment trust layer: keeps irreversible stablecoin payouts away from bad actors "
            "without slowing honest vendors.",
            "business": s.business_name,
            "owner": s.owner_name,
            "today": e.today.isoformat(),
            "region": s.region,
            "llm_mode": e.llm.mode,
            "llm_provider": e.llm.provider(),
            "llm_model": e.llm.model_name,
            "scorer": getattr(scorer, "name", "?"),
            "model": f"{getattr(scorer, 'name', '?')} {getattr(scorer, 'version', '')}".strip(),
            "model_version": getattr(scorer, "version", None),
            "policy_mode": "cedar" if cedar_available() else "python-mirror",
            "settlement_adapter": e.adapter.name,
            "settlement_network": e.adapter.network,
            "database": self.store.backend,
            "attachments": self.attachments.backend,
            "vendors": len(e.vendors),
            "runs": len(e.runs),
            "limits_cents": {
                "approval": e.limits.approval_limit_cents,
                "fast_pay": e.limits.fast_pay_limit_cents,
                "single_payment": e.limits.single_payment_limit_cents,
                "batch": e.limits.batch_limit_cents,
            },
        }

    def netz(self) -> dict[str, Any]:
        from hm_llm.clients import akamai_limiter
        from hm_llm.settings import get_llm_settings
        from vouch.pipeline import LLM_NODES, STAGES

        e = self.engine
        llm_settings = get_llm_settings()
        shared_limiter = akamai_limiter(llm_settings)
        timings = {
            k: {"n": len(v), "p50_ms": _pct(v, 0.5), "p95_ms": _pct(v, 0.95)}
            for k, v in sorted(e.timings.items())
        }
        cards = [c for r in e.runs.values() for c in r.card_list()]
        hops = []
        for a, b in itertools.pairwise(STAGES):
            t = timings.get(f"node:{b}", {})
            hops.append(
                {
                    "id": f"{a}->{b}",
                    "from": a,
                    "to": b,
                    "p50_ms": t.get("p50_ms") or 0,
                    "p95_ms": t.get("p95_ms") or 0,
                    "private": b not in LLM_NODES,
                    "llm": b in LLM_NODES,
                }
            )
        stats = e.llm.stats
        n_cards = max(1, len(cards))
        policy_total = sum(1 for c in cards if c.policy)
        policy_passed = sum(1 for c in cards if c.policy and c.policy.allowed)
        all_node = [ms for k, v in e.timings.items() if k.startswith("node:") for ms in v]
        scorer = e.scorer()
        return {
            "service": "vouch-api",
            "version": __version__,
            "runs": len(e.runs),
            "cards": len(cards),
            "paid": sum(c.status == CardStatus.PAID for c in cards),
            "held": sum(c.status == CardStatus.HOLD for c in cards),
            "llm": {
                "mode": e.llm.mode,
                "provider": e.llm.provider(),
                "model": e.llm.model_name,
                "limits": {
                    "rpm": llm_settings.llm_requests_per_minute,
                    "client_rpm": self.settings.llm_rpm,
                    "context_tokens": llm_settings.llm_max_context_tokens,
                    "output_tokens": llm_settings.llm_max_output_tokens,
                },
                "rate_limit_remaining": shared_limiter.remaining,
                "rate_limit": e.llm.limiter.snapshot(),
                "requests": e.llm.request_stats.snapshot(),
                **stats.to_dict(),
            },
            "latency": timings,
            "p50_ms": _pct(all_node, 0.5),
            "p95_ms": _pct(all_node, 0.95),
            "hops": hops,
            "model_version": f"{getattr(scorer, 'name', '?')} {getattr(scorer, 'version', '')}".strip(),
            "tokens": {
                "prompt_today": stats.input_tokens,
                "completion_today": stats.output_tokens,
                "per_payment_avg": round((stats.input_tokens + stats.output_tokens) / n_cards, 1),
            },
            "policy_checks": {"passed": policy_passed, "total": policy_total},
            "policy_engine": "cedar" if cedar_available() else "python-mirror",
            "region": self.settings.region,
            "updated_at": iso(utcnow()),
            "explanations": {
                "llm": sum(c.explanation_source == "llm" for c in cards),
                "template": sum(c.explanation_source == "template" for c in cards),
            },
            "scorer": getattr(scorer, "name", "?"),
            "settlement": {"adapter": e.adapter.name, "network": e.adapter.network},
            "store": self.store.counts(),
        }

    def run_redteam(self, force: bool = False) -> dict[str, Any]:
        from vouch.redteam import run_suite

        if self.redteam is not None and not force:
            return self.redteam
        result = run_suite(self.engine.settings, scorer=self.engine.scorer())
        now = datetime.now(UTC)
        result["ran_at"] = now.date().isoformat()
        result["run_at"] = iso(now)
        result["model_version"] = self.info()["model"]
        for case in result["cases"]:
            case.setdefault("prompt", case.get("attack"))
            detail = case.get("detail") or {}
            reasons = detail.get("reasons") or detail.get("second_reasons") or []
            case.setdefault(
                "rule", reasons[0] if reasons else ("blocked" if case["blocked"] else "NOT BLOCKED")
            )
        self.redteam = result
        return result


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[min(int(p * len(s)), len(s) - 1)], 1)


def _document_record(doc: ExtractedDocument) -> dict[str, Any]:
    return {
        "filename": doc.filename,
        "kind": doc.kind,
        "sha256": doc.sha256,
        "extractor": doc.extractor,
        "warnings": list(doc.warnings),
    }


__all__ = ["NotFoundError", "VouchService"]
