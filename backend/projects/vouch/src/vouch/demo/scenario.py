"""The demo scenario: eight synthetic invoices (six vendors) through the real pipeline."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ..models import PaymentRecord
from ..service import VouchService
from .samples import Sample, build_samples
from .vendors import build_directory

log = logging.getLogger(__name__)

DEMO_IDS = {
    "reyes": "pay-001",
    "warsaw": "pay-002",
    "midwest": "pay-003",
    "midwest-dup": "pay-004",
    "brightline-bl-3307": "pay-005",
    "brightline-bl-3308": "pay-006",
    "nova": "pay-007",
    "santa-rita": "pay-008",
}


async def seed_demo(
    service: VouchService, *, reset: bool = True, now: datetime | None = None
) -> list[tuple[Sample, PaymentRecord]]:
    now = now or datetime.now(UTC)
    if reset:
        service.reset_payments()
    service.load_vendors(build_directory(now.date()))
    if service.llm.embedder_or_none() is not None:
        try:
            service.index_vendor_embeddings()
        except Exception as exc:  # pragma: no cover - network
            log.warning("vendor embedding index skipped: %s", exc)
    results: list[tuple[Sample, PaymentRecord]] = []
    for sample in build_samples(now):
        received = now - sample.received_offset
        record = await service.intake(sample.request, received_at=received, payment_id=DEMO_IDS[sample.key])
        results.append((sample, record))
    return results


def summarize(results: list[tuple[Sample, PaymentRecord]]) -> str:
    lines = []
    for s, p in results:
        ok = "ok " if (p.status == s.expected_status and p.risk == s.expected_risk) else "!! "
        llm = "llm" if p.trace and (p.trace.reader_used_llm or p.trace.writer_used_llm) else "tpl"
        lines.append(
            f"{ok}{p.id} {p.vendor_name[:24]:24} {p.invoice_number:13} ${p.amount_cents / 100:>9,.2f} "
            f"{p.status:11} {p.risk:20} trust={p.trust_score:3} [{llm}] {p.reason[:70]}"
        )
    return "\n".join(lines)
