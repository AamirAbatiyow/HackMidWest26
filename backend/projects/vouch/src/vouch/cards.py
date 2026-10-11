"""PaymentCard: everything the owner (and the frontend) needs to decide on one payment."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from vouch.contracts import SenderFindings, VendorResolution
from vouch.decider.classify import IntakeClassification
from vouch.domain import CardStatus, Invoice, ModelScores, PolicyOutcome, Resolution, Vendor


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Investigation(BaseModel):
    investigator: str  # which class-specific investigator looked at it
    summary: str
    evidence: list[str] = Field(default_factory=list)  # fact keys / deterministic flags it relied on
    vendor_questions: list[str] = Field(default_factory=list)
    recommended_action: str = "verify"
    source: Literal["llm", "template"] = "template"
    provenance_ok: bool = True


class PaymentCard(BaseModel):
    id: str
    run_id: str
    invoice: Invoice
    vendor: Vendor | None = None
    resolution: VendorResolution | None = None  # deterministic vendor match (known / new / uncertain)
    sender: SenderFindings | None = None  # deterministic email sender check (SPF/DKIM/DMARC, lookalikes)
    intake: IntakeClassification | None = None  # advisory routing (decider / hackathon-chat / deterministic)
    payable_cents: int = 0
    checks: dict[str, Any] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)
    features: dict[str, float] = Field(default_factory=dict)
    categorical: dict[str, str] = Field(default_factory=dict)
    scores: ModelScores | None = None
    investigation: Investigation | None = None
    policy: PolicyOutcome | None = None
    funding: dict[str, Any] | None = None
    facts: dict[str, str] = Field(default_factory=dict)
    explanation: str = ""
    explanation_source: Literal["llm", "template", "pending"] = "pending"
    status: CardStatus = CardStatus.PENDING
    resolutions: list[Resolution] = Field(default_factory=list)
    receipt: dict[str, Any] | None = None
    timeline: list[dict[str, Any]] = Field(default_factory=list)

    def log(self, event: str, **data: Any) -> None:
        self.timeline.append({"at": now_iso(), "event": event, **data})

    def has_resolution(self, kind: str) -> bool:
        return any(r.kind == kind for r in self.resolutions)

    def summary(self) -> dict[str, Any]:
        """Compact view for list endpoints."""
        s = self.scores
        return {
            "id": self.id,
            "vendor": self.invoice.vendor_name,
            "invoice_number": self.invoice.invoice_number,
            "amount_cents": self.invoice.amount_cents,
            "payable_cents": self.payable_cents,
            "due_date": self.invoice.due_date.isoformat(),
            "status": self.status,
            "lane": self.policy.lane if self.policy else None,
            "vendor_match": self.resolution.status if self.resolution else None,
            "sender_flags": self.sender.flags if self.sender else [],
            "risk_class": s.top_class if s else None,
            "risk": s.risk if s else None,
            "legitimacy": s.legitimacy if s else None,
            "anomaly": s.anomaly if s else None,
            "lime": s.lime[:5] if s else [],
            "policy_reasons": self.policy.reasons if self.policy else [],
            "required_actions": self.policy.required_actions if self.policy else [],
            "explanation": self.explanation,
            "funding": self.funding,
            "tx": self.receipt,
        }
