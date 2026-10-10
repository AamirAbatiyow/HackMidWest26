"""Typed state shared by the graph nodes (passed through Strands ``invocation_state``)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from ..detectors.scoring import ScoreResult
from ..models import (
    BankChangeFindings,
    ChecklistItem,
    DupSplitFindings,
    EmailEnvelope,
    ExtractedDocument,
    IntakeRequest,
    ParsedInvoice,
    PaymentRecord,
    PolicyResult,
    RingFindings,
    SenderFindings,
    Vendor,
    VendorResolution,
)


@dataclass
class RunContext:
    # inputs
    request: IntakeRequest
    envelope: EmailEnvelope | None
    documents: list[ExtractedDocument]
    text: str
    received_at: datetime
    today: date
    source: str
    existing: list[PaymentRecord]
    payment_id: str
    run_id: str | None = None
    # services (duck-typed to avoid import cycles)
    services: Any = None
    # node outputs
    parsed: ParsedInvoice | None = None
    resolution: VendorResolution | None = None
    vendor: Vendor | None = None
    sender: SenderFindings | None = None
    bank_change: BankChangeFindings | None = None
    dup_split: DupSplitFindings | None = None
    ring: RingFindings | None = None
    score: ScoreResult | None = None
    policy: PolicyResult | None = None
    reason: str = ""
    checklist: list[ChecklistItem] = field(default_factory=list)
    timings_ms: dict[str, int] = field(default_factory=dict)
    trace: dict[str, Any] = field(
        default_factory=lambda: {"fallbacks": [], "reader_used_llm": False, "writer_used_llm": False}
    )
    document_sha256: str | None = None
