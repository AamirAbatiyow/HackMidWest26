"""The Vouch graph: reader → screener → {bank, dup/split, ring} → scorer → policy → writer.

Built with Strands ``GraphBuilder``; runs in ``live`` (Akamai chat model for reader/writer) or
``template`` mode with identical deterministic checks in between.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from strands.multiagent import GraphBuilder
from strands.multiagent.graph import GraphState

from ..audit import AuditStore, new_id
from ..config import Settings
from ..intake import combine_documents, envelope_from_headers, extract_file, intake_body_text
from ..intake.amounts import format_cents
from ..llm import LlmRuntime
from ..models import (
    ExtractedDocument,
    IntakeRequest,
    LlmTrace,
    PaymentRecord,
    TimelineEvent,
    iso,
)
from ..storage import AttachmentStore
from ..vendors import VendorDirectory
from ..vendors.embeddings import EmbeddingIndex
from . import nodes
from .context import RunContext

log = logging.getLogger(__name__)

NODE_ORDER = ["reader", "screener", "check_bank", "check_dup", "check_ring", "scorer", "policy", "writer"]


@dataclass
class Services:
    settings: Settings
    llm: LlmRuntime
    directory: VendorDirectory
    embedding_index: EmbeddingIndex
    store: AuditStore
    attachments: AttachmentStore


def build_graph():
    b = GraphBuilder()
    b.add_node(nodes.StepNode("reader", nodes.reader), "reader")
    b.add_node(nodes.StepNode("screener", nodes.screener), "screener")
    b.add_node(nodes.StepNode("check_bank", nodes.check_bank), "check_bank")
    b.add_node(nodes.StepNode("check_dup", nodes.check_dup), "check_dup")
    b.add_node(nodes.StepNode("check_ring", nodes.check_ring), "check_ring")
    b.add_node(nodes.StepNode("scorer", nodes.scorer), "scorer")
    b.add_node(nodes.StepNode("policy", nodes.policy), "policy")
    b.add_node(nodes.StepNode("writer", nodes.writer), "writer")
    b.add_edge("reader", "screener")
    for check in ("check_bank", "check_dup", "check_ring"):
        b.add_edge("screener", check)

    def all_checks_done(state: GraphState) -> bool:
        done = {n.node_id for n in state.completed_nodes}
        return {"check_bank", "check_dup", "check_ring"} <= done

    for check in ("check_bank", "check_dup", "check_ring"):
        b.add_edge(check, "scorer", condition=all_checks_done)
    b.add_edge("scorer", "policy")
    b.add_edge("policy", "writer")
    b.set_entry_point("reader")
    b.set_max_node_executions(len(NODE_ORDER) * 2)
    b.set_execution_timeout(180.0)
    return b.build()


class VouchPipeline:
    def __init__(self, services: Services) -> None:
        self.svc = services

    async def run_intake(
        self,
        request: IntakeRequest,
        *,
        existing: list[PaymentRecord],
        payment_id: str | None = None,
        received_at: datetime | None = None,
    ) -> tuple[PaymentRecord, RunContext]:
        svc = self.svc
        received = received_at or request.received_at or datetime.now(UTC)
        if received.tzinfo is None:
            received = received.replace(tzinfo=UTC)
        pid = payment_id or new_id("pay")
        run_id = svc.store.start_run(
            svc.llm.mode, svc.llm.model_name if svc.llm.live else None, request.source
        )

        envelope = envelope_from_headers(request.headers) if request.headers else None
        documents: list[ExtractedDocument] = []
        body = intake_body_text(request)
        if body.strip():
            documents.append(
                ExtractedDocument(filename="email-body", kind="email_body", text=body, extractor="email")
            )
        first_sha: str | None = None
        for att in request.attachments:
            data = base64.b64decode(att.data_b64) if att.data_b64 else b""
            doc = extract_file(data, att.filename, att.content_type)
            documents.append(doc)
            first_sha = first_sha or doc.sha256
            key = AttachmentStore.key_for(pid, doc.sha256, att.filename)
            try:
                storage_key = svc.attachments.put(key, data, att.content_type)
            except Exception as exc:  # pragma: no cover - storage outage
                log.warning("attachment storage failed: %s", exc)
                storage_key = None
            svc.store.record_document(
                run_id, pid, att.filename, doc.kind, doc.sha256, doc.extractor, doc.text, storage_key
            )
        text = combine_documents(documents)

        ctx = RunContext(
            request=request,
            envelope=envelope,
            documents=documents,
            text=text,
            received_at=received,
            today=received.date(),
            source=request.source,
            existing=existing,
            payment_id=pid,
            run_id=run_id,
            services=svc,
            document_sha256=first_sha,
        )
        graph = build_graph()
        result = await graph.invoke_async("vouch this invoice", invocation_state={"ctx": ctx})
        if str(result.status).lower().endswith("failed"):
            raise RuntimeError(f"graph failed: {result}")
        record = self._to_record(ctx)
        svc.store.save_payment(record)
        svc.store.record_decision(run_id, record)
        if ctx.policy:
            for action in ctx.policy.allowed_actions:
                principal, act = action.split(":", 1)
                svc.store.record_policy(
                    run_id, pid, ctx.policy.engine, principal, act, True, ctx.policy.rules_fired[:1]
                )
            for action in ctx.policy.denied_actions:
                principal, act = action.split(":", 1)
                svc.store.record_policy(
                    run_id, pid, ctx.policy.engine, principal, act, False, ["DEFAULT-DENY"]
                )
        svc.store.finish_run(run_id, pid, "ok", ctx.timings_ms, ctx.trace)
        return record, ctx

    # ------------------------------------------------------------------ record ----
    def _to_record(self, ctx: RunContext) -> PaymentRecord:
        assert (
            ctx.parsed
            and ctx.resolution
            and ctx.score
            and ctx.policy
            and ctx.bank_change
            and ctx.dup_split
            and ctx.ring
        )
        p, v, s = ctx.parsed, ctx.vendor, ctx.score
        due = p.due_date or (ctx.received_at + timedelta(days=14)).date()
        vendor_id = v.id if v else f"v-new-{ctx.payment_id[-6:]}"
        timeline: list[TimelineEvent] = []
        inv = p.fields.invoice_number or "—"
        detail = (
            f"From {ctx.envelope.from_addr}"
            if ctx.envelope and ctx.envelope.from_addr
            else f"Uploaded {ctx.documents[0].filename}"
            if ctx.documents
            else None
        )
        timeline.append(
            TimelineEvent(
                id="t1",
                date=iso(ctx.received_at) or "",
                title=f"Invoice {inv} received",
                detail=detail,
                kind="payment",
            )
        )
        if ctx.bank_change.changed and v and v.current_bank:
            who = (
                f"Requested by {ctx.bank_change.requested_by}"
                if ctx.bank_change.requested_by
                else "Listed on this invoice"
            )
            timeline.append(
                TimelineEvent(
                    id="t2",
                    date=iso(v.current_bank.since) or "",
                    title="Bank details changed",
                    detail=who
                    + (
                        " (new sender)"
                        if ctx.sender and "new_sender_for_known_vendor" in ctx.sender.flags
                        else ""
                    ),
                    kind="change",
                )
            )
        if ctx.ring.shared_bank_with:
            timeline.append(
                TimelineEvent(
                    id="t3",
                    date=iso(ctx.received_at) or "",
                    title=f"Bank account linked to {len(ctx.ring.shared_bank_with)} other vendor(s)",
                    detail=", ".join(ctx.ring.shared_bank_with),
                    kind="check",
                )
            )
        if v:
            for i, h in enumerate(v.history[:3]):
                timeline.append(
                    TimelineEvent(
                        id=f"h{i}",
                        date=iso(h.date) or "",
                        title=f"Paid {format_cents(h.amount_cents)}",
                        detail=f"Invoice {h.invoice_number}" + (f" · {h.detail}" if h.detail else ""),
                        kind="payment",
                    )
                )
            if v.verified_by_callback and v.payments_completed == 0:
                timeline.append(
                    TimelineEvent(
                        id="tv",
                        date=iso(v.since) or "",
                        title="Bank account verified",
                        detail="Call-back with " + (v.contact_name or "the vendor"),
                        kind="check",
                    )
                )
            timeline.append(
                TimelineEvent(
                    id="to",
                    date=iso(v.since) or "",
                    title="Vendor onboarded" if v.payments_completed else "Vendor added",
                    detail=v.onboarding_note,
                    kind="onboard",
                )
            )
        timeline.sort(key=lambda t: t.date, reverse=True)

        trace = LlmTrace(
            mode=self.svc.llm.mode,
            model=self.svc.llm.model_name,
            reader_used_llm=bool(ctx.trace.get("reader_used_llm")),
            writer_used_llm=bool(ctx.trace.get("writer_used_llm")),
            fallbacks=list(ctx.trace.get("fallbacks", [])),
            latency_ms=sum(ctx.timings_ms.values()),
        )
        return PaymentRecord(
            id=ctx.payment_id,
            vendor_id=vendor_id,
            vendor_name=ctx.resolution.vendor_name,
            vendor_city=v.city if v else "",
            vendor_country=v.country if v else "US",
            vendor_since=iso(v.since) if v else iso(ctx.received_at) or "",
            vendor_payments_completed=v.payments_completed if v else 0,
            invoice_number=inv,
            amount_cents=p.amount_cents or 0,
            currency=p.currency,
            due_date=iso(due) or "",
            invoice_date=iso(p.invoice_date),
            status=s.status,
            lifecycle="pending",
            risk=s.risk,
            trust_score=s.trust,
            reason=ctx.reason,
            fast_pay_eligible=s.fast_pay_eligible,
            source=ctx.source,  # type: ignore[arg-type]
            received_at=iso(ctx.received_at) or "",
            duplicate_of=ctx.dup_split.duplicate_of,
            split_with=ctx.dup_split.split_with[0] if ctx.dup_split.split_with else None,
            evidence=s.evidence,
            timeline=timeline,
            checklist=ctx.checklist,
            ring=ctx.ring.graph,
            policy=ctx.policy,
            sender=ctx.sender,
            vendor_resolution=ctx.resolution,
            bank_change=ctx.bank_change,
            dup_split=ctx.dup_split,
            ring_findings=ctx.ring,
            parsed=p,
            trace=trace,
            run_id=ctx.run_id,
            document_sha256=ctx.document_sha256,
            bank_account_last4=p.bank_account_last4,
        )
