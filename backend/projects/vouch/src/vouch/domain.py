"""Domain records. Money is always integer cents (`*_cents: int`); there are no floats for amounts."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class RiskClass(StrEnum):
    HONEST = "honest"
    ATO_BEC = "ato_bec"  # account takeover / business email compromise
    INSIDER = "insider"  # duplicates, splits, creeping amounts, no PO/delivery
    FAKE_VENDOR = "fake_vendor"  # synthetic vendors, rings sharing bank/address/phone/tax id


RISK_CLASSES = [RiskClass.ATO_BEC, RiskClass.INSIDER, RiskClass.FAKE_VENDOR]


class Lane(StrEnum):
    FAST_PAY = "fast_pay"  # verified small vendor: paid right away under the owner's standing rule
    STANDARD = "standard"  # clean, waits for the owner's one-click batch approval
    HOLD = "hold"  # needs a human resolution step; never an automatic denial


class CardStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"  # policy allows; awaiting batch approval
    HOLD = "hold"
    APPROVED = "approved"
    PAID = "paid"
    FAILED = "failed"
    CREDIT = "credit_applied"  # credit note netted against the vendor's invoices


class PastPayment(BaseModel):
    amount_cents: int
    days_ago: int
    invoice_number: str = ""


class Vendor(BaseModel):
    id: str
    name: str
    country: str
    currency: str = "USD"
    category: str = "goods"
    email: str
    phone: str
    address: str
    tax_id: str
    bank_account: str  # masked account / IBAN-like identifier on the vendor master file
    bank_country: str
    created_days_ago: int
    history: list[PastPayment] = Field(default_factory=list)
    # Bank-detail change on the master file and whether someone confirmed it out-of-band
    # (call-back to the phone number already on file, not the one in the change request).
    bank_changed_days_ago: int | None = None
    bank_change_confirmed_oob: bool = False
    previous_bank_account: str | None = None
    contact_changed_days_ago: int | None = None
    oob_verified: bool = False  # vendor identity verified out-of-band at onboarding
    destination_tag: int = 0  # XRPL destination tag on the shared demo receiving account


class LineItem(BaseModel):
    description: str
    quantity: int = 1
    unit_cents: int

    @property
    def total_cents(self) -> int:
        return self.quantity * self.unit_cents


class Invoice(BaseModel):
    id: str
    vendor_id: str | None = None
    vendor_name: str
    invoice_number: str
    amount_cents: int
    currency: str = "USD"
    issue_date: date
    due_date: date
    po_number: str | None = None
    delivery_confirmed: bool = False
    bank_account: str | None = None  # bank details printed on the invoice (may differ from master!)
    remit_email: str | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    is_credit_note: bool = False
    # Early-payment terms, e.g. 2/10 net 30 -> discount_bps=200, discount_days=10.
    discount_bps: int = 0
    discount_days: int = 0
    submitted_by: str = "ap-clerk-1"
    raw_text: str = ""
    source: Literal["json", "text", "pdf_text", "email", "upload", "synthetic"] = "json"
    # Who authored the amount. Anything other than "kernel"/"source" must never reach settlement.
    amount_origin: Literal["source", "kernel", "llm", "missing"] = "source"


class Labels(BaseModel):
    """Ground truth from the synthetic generator (never shown to the pipeline)."""

    risk_class: RiskClass
    pattern: str
    honest_unusual: bool = False


class ModelScores(BaseModel):
    risk: dict[str, float]  # per-class probability from the risk heads
    anomaly: float  # autoencoder reconstruction score, 0..1 (percentile vs honest training data)
    legitimacy: float  # confidence the vendor/invoice is legitimate, 0..1
    ring_score: float = 0.0  # graph signal: shared attributes with other vendors
    top_class: str
    model_version: str
    scorer: str  # "inference-service", "local-torch", or "heuristic-fallback"
    lime: list[dict[str, Any]] = Field(default_factory=list)  # [{feature, weight}] for top_class
    lime_class: str | None = None


class PolicyOutcome(BaseModel):
    lane: Lane
    allowed: bool
    reasons: list[str]
    required_actions: list[str] = Field(default_factory=list)


class Resolution(BaseModel):
    kind: Literal[
        "confirm_bank", "resolve_risk", "appeal", "owner_hold", "release_hold", "limit_override", "approve"
    ]
    actor: str
    note: str = ""
    method: str | None = None  # e.g. "call-back to phone on file"
    at: str = ""
