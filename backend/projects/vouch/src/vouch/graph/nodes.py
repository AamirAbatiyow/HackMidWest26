"""Graph nodes. Each is a Strands ``MultiAgentBase`` so the whole pipeline runs as a Strands
``Graph``; typed state travels in ``invocation_state["ctx"]`` (a ``RunContext``), never as
free text between nodes. Only ``reader`` and ``writer`` call the model.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from strands.multiagent.base import MultiAgentBase, MultiAgentResult, Status
from strands.types.event_loop import Metrics, Usage

from ..detectors import Candidate, ScoreInputs, detect_bank_change, detect_dup_split, score
from ..intake.amounts import email_domain, format_cents
from ..llm.reader import template_structure
from ..llm.templates import WriterContext
from ..llm.writer import template_write
from ..policy import PaymentAttrs, evaluate_payment
from ..sender import check_sender
from ..vendors import detect_ring, resolve_vendor
from .context import RunContext

NodeFn = Callable[[RunContext], Awaitable[None]]


class StepNode(MultiAgentBase):
    """A deterministic or model-backed step operating on the shared RunContext."""

    def __init__(self, name: str, fn: NodeFn) -> None:
        super().__init__()
        self.name = name
        self.fn = fn

    async def invoke_async(
        self, task: Any, invocation_state: dict[str, Any] | None = None, **kwargs: Any
    ) -> MultiAgentResult:
        ctx: RunContext = (invocation_state or {})["ctx"]
        t0 = time.monotonic()
        await self.fn(ctx)
        ms = int((time.monotonic() - t0) * 1000)
        ctx.timings_ms[self.name] = ms
        return MultiAgentResult(
            status=Status.COMPLETED,
            results={},
            accumulated_usage=Usage(inputTokens=0, outputTokens=0, totalTokens=0),
            accumulated_metrics=Metrics(latencyMs=ms),
            execution_count=1,
            execution_time=ms,
        )

    def serialize_state(self) -> dict[str, Any]:  # pragma: no cover - sessions unused
        return {}

    def deserialize_state(self, payload: dict[str, Any]) -> None:  # pragma: no cover
        return None


# ----------------------------------------------------------------- steps ----


async def reader(ctx: RunContext) -> None:
    """Structure the extracted text. Live: Strands structured output; else regex. Numbers in code."""
    svc = ctx.services
    llm_reader = svc.llm.reader()
    if llm_reader is not None:
        parsed, trace = await llm_reader.structure(ctx.text)
    else:
        parsed, trace = template_structure(ctx.text)
    ctx.parsed = parsed
    ctx.trace["reader_used_llm"] = trace.get("reader_used_llm", False)
    ctx.trace["fallbacks"] += trace.get("fallbacks", [])
    ctx.trace["reader_latency_ms"] = trace.get("latency_ms", 0)


async def screener(ctx: RunContext) -> None:
    """Resolve the vendor (known/new/uncertain) and check who sent the email."""
    svc = ctx.services
    assert ctx.parsed is not None
    sender_domain = email_domain(ctx.envelope.from_addr) if ctx.envelope else None
    ctx.resolution = resolve_vendor(
        ctx.parsed,
        svc.directory,
        sender_domain=sender_domain,
        embedder=svc.llm.embedder_or_none(),
        index=svc.embedding_index,
    )
    ctx.vendor = svc.directory.get(ctx.resolution.vendor_id) if ctx.resolution.vendor_id else None
    ctx.sender = check_sender(ctx.envelope, svc.directory.all(), ctx.vendor)


async def check_bank(ctx: RunContext) -> None:
    assert ctx.parsed is not None
    ctx.bank_change = detect_bank_change(ctx.parsed, ctx.vendor, ctx.sender, ctx.today)


async def check_dup(ctx: RunContext) -> None:
    assert ctx.parsed is not None and ctx.resolution is not None
    svc = ctx.services
    vendor_key = ctx.resolution.vendor_id or f"candidate:{ctx.resolution.vendor_name.lower()}"
    cand = Candidate(
        id=ctx.payment_id,
        vendor_id=vendor_key,
        invoice_number=ctx.parsed.fields.invoice_number or "",
        amount_cents=ctx.parsed.amount_cents or 0,
        received_at=ctx.received_at,
        document_sha256=ctx.document_sha256,
    )
    existing = [
        Candidate(
            id=p.id,
            vendor_id=p.vendor_id,
            invoice_number=p.invoice_number,
            amount_cents=p.amount_cents,
            received_at=_parse_dt(p.received_at),
            document_sha256=p.document_sha256,
        )
        for p in ctx.existing
        if p.lifecycle != "settled"
    ]
    ctx.dup_split = detect_dup_split(cand, existing, svc.settings.approval_limit_cents)


async def check_ring(ctx: RunContext) -> None:
    assert ctx.parsed is not None and ctx.resolution is not None
    ctx.ring = detect_ring(ctx.parsed, ctx.resolution, ctx.services.directory)


async def scorer(ctx: RunContext) -> None:
    assert ctx.parsed and ctx.resolution and ctx.bank_change and ctx.dup_split and ctx.ring
    svc = ctx.services
    related = {p.id: p.invoice_number for p in ctx.existing}
    ctx.score = score(
        ScoreInputs(
            parsed=ctx.parsed,
            vendor=ctx.vendor,
            resolution=ctx.resolution,
            sender=ctx.sender,
            bank_change=ctx.bank_change,
            dup_split=ctx.dup_split,
            ring=ctx.ring,
            today=ctx.today,
            approval_limit_cents=svc.settings.approval_limit_cents,
            new_vendor_limit_cents=svc.settings.new_vendor_limit_cents,
            related_invoice_numbers=related,
        )
    )


async def policy(ctx: RunContext) -> None:
    assert ctx.score and ctx.parsed and ctx.bank_change and ctx.resolution
    svc = ctx.services
    attrs = PaymentAttrs(
        status=ctx.score.status,
        lifecycle="pending",
        risk=ctx.score.risk,
        trust_score=ctx.score.trust,
        fast_pay_eligible=ctx.score.fast_pay_eligible,
        bank_changed=ctx.bank_change.changed,
        bank_change_verified=bool(ctx.bank_change.requester_verified),
        amount_cents=ctx.parsed.amount_cents or 0,
        vendor_known=ctx.resolution.status == "known",
    )
    ctx.policy = evaluate_payment(attrs, svc.settings.approval_limit_cents, payment_id=ctx.payment_id)


async def writer(ctx: RunContext) -> None:
    assert ctx.score and ctx.parsed and ctx.resolution and ctx.bank_change and ctx.dup_split and ctx.ring
    svc = ctx.services
    v = ctx.vendor
    related = {p.id: p.invoice_number for p in ctx.existing}
    wctx = WriterContext(
        vendor_name=ctx.resolution.vendor_name,
        amount_text=format_cents(ctx.parsed.amount_cents or 0, ctx.parsed.currency),
        status=ctx.score.status,
        risk=ctx.score.risk,
        vendor_known=ctx.resolution.status == "known",
        payments_completed=v.payments_completed if v else 0,
        concerns=[e.label for e in ctx.score.evidence if e.direction == "concern"],
        reassuring=[e.label for e in ctx.score.evidence if e.direction == "reassuring"],
        bank_changed=ctx.bank_change.changed,
        days_since_change=ctx.bank_change.days_since_change,
        contact_name=v.contact_name if v else None,
        contact_phone_masked=v.contact_phone_masked if v else None,
        duplicate_of_invoice=related.get(ctx.dup_split.duplicate_of) if ctx.dup_split.duplicate_of else None,
        split_with_invoices=[related.get(i, i) for i in ctx.dup_split.split_with],
        combined_text=format_cents(ctx.dup_split.combined_cents) if ctx.dup_split.combined_cents else None,
        approval_limit_text=format_cents(svc.settings.approval_limit_cents),
        shared_bank_with=ctx.ring.shared_bank_with,
        shared_phone_with=ctx.ring.shared_phone_with,
        new_vendor_verified=bool(v and (v.verified_by_callback or v.registration_verified)),
        invoice_number=ctx.parsed.fields.invoice_number or "",
        sender_flags=ctx.sender.flags if ctx.sender else [],
    )
    llm_writer = svc.llm.writer()
    if llm_writer is not None:
        reason, checklist, trace = await llm_writer.write(wctx)
    else:
        reason, checklist, trace = template_write(wctx)
    ctx.reason, ctx.checklist = reason, checklist
    ctx.trace["writer_used_llm"] = trace.get("writer_used_llm", False)
    ctx.trace["fallbacks"] += trace.get("fallbacks", [])
    ctx.trace["writer_latency_ms"] = trace.get("latency_ms", 0)


# --------------------------------------------------------------- helpers ----


def _parse_dt(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
