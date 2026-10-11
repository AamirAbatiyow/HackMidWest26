"""Contract models that sit around the payment engine: email/file intake, the deterministic sender
check, vendor resolution, and the shapes the frontend consumes (payments, receipts, ring graphs).

Money is always integer cents parsed in code (see `vouch.kernel`). Nothing in here is authored by an
LLM; the LLM may only quote strings from the invoice text and the kernel verifies every quote.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field

VouchStatus = Literal["vouched", "quick_check", "verify"]
Lifecycle = Literal["pending", "approved", "held", "appealed", "settled"]
RiskType = Literal["changed_bank", "duplicate_or_split", "unrecognized_vendor", "none"]
Source = Literal["email", "upload", "json"]
Direction = Literal["concern", "reassuring"]


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | date | None) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return dt.isoformat()


def digits_only(text: str | None) -> str | None:
    if not text:
        return None
    d = re.sub(r"\D", "", text)
    return d or None


def email_domain(addr: str | None) -> str | None:
    if not addr or "@" not in addr:
        return None
    return addr.rsplit("@", 1)[1].strip().lower().strip(">") or None


# ---------------------------------------------------------------- intake ----


class Attachment(BaseModel):
    filename: str
    content_type: str = "application/octet-stream"
    data_b64: str = ""
    sha256: str = ""
    size: int = 0


class ExtractedTable(BaseModel):
    source: str
    rows: list[list[str]]


class ExtractedDocument(BaseModel):
    """Deterministic extraction output for one file (or the email body)."""

    filename: str
    kind: Literal["pdf", "image", "xlsx", "csv", "text", "email_body", "unknown"]
    text: str
    tables: list[ExtractedTable] = Field(default_factory=list)
    extractor: str
    warnings: list[str] = Field(default_factory=list)
    sha256: str = ""


class EmailEnvelope(BaseModel):
    from_addr: str = ""
    from_name: str = ""
    reply_to: str = ""
    to: str = ""
    subject: str = ""
    date: str = ""
    message_id: str = ""
    authentication_results: list[str] = Field(default_factory=list)
    received_spf: str = ""
    headers: dict[str, str] = Field(default_factory=dict)


class IntakeRequest(BaseModel):
    """JSON intake body. Attachments carry base64 payloads."""

    headers: dict[str, str] = Field(default_factory=dict)
    body_text: str = ""
    body_html: str = ""
    attachments: list[Attachment] = Field(default_factory=list)
    source: Source = "email"
    received_at: datetime | None = None
    submitted_by: str = "ap-inbox"
    delivery_confirmed: bool = False
    po_number: str | None = None


class VendorClaim(BaseModel):
    """Identity the invoice *claims* (regex-extracted strings, used only to look the vendor up)."""

    name: str | None = None
    email: str | None = None
    tax_id: str | None = None
    bank_account: str | None = None
    phone: str | None = None
    address: str | None = None


# ---------------------------------------------------------- sender check ----


class AuthResults(BaseModel):
    spf: str = "none"
    dkim: str = "none"
    dmarc: str = "none"
    dkim_domain: str | None = None
    spf_domain: str | None = None
    raw: list[str] = Field(default_factory=list)


class LookalikeFinding(BaseModel):
    domain: str
    closest_known_domain: str | None = None
    distance: int | None = None
    homoglyph_normalized_match: bool = False
    is_lookalike: bool = False
    is_known: bool = False
    detail: str = ""


class SenderFindings(BaseModel):
    checked: bool = False  # False when the invoice did not arrive by email (upload / JSON)
    from_addr: str = ""
    from_domain: str = ""
    reply_to: str = ""
    reply_to_domain: str = ""
    reply_to_mismatch: bool = False
    display_name_mismatch: bool = False
    auth: AuthResults = Field(default_factory=AuthResults)
    auth_pass: bool = False
    lookalike: LookalikeFinding | None = None
    flags: list[str] = Field(default_factory=list)
    risk: float = 0.0  # 0..1 deterministic sender risk

    @property
    def suspicious(self) -> bool:
        """Hard sender problems that put a card on hold (never a denial)."""
        hard = {"lookalike_domain", "reply_to_lookalike_domain", "dmarc_fail", "spf_fail", "dkim_fail"}
        return bool(hard & set(self.flags)) or (self.reply_to_mismatch and self.risk >= 0.5)


# ------------------------------------------------------------- vendors ----

VendorMatchStatus = Literal["known", "new", "uncertain"]


class VendorCandidate(BaseModel):
    vendor_id: str
    name: str
    score: float
    matched_on: str


class VendorResolution(BaseModel):
    status: VendorMatchStatus
    vendor_id: str | None = None
    vendor_name: str
    matched_on: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    candidates: list[VendorCandidate] = Field(default_factory=list)
    embedding_used: bool = False
    notes: list[str] = Field(default_factory=list)


# ------------------------------------------------------- frontend views ----


class RingNode(BaseModel):
    id: str
    label: str
    kind: Literal["vendor", "bank", "phone", "address"]
    focus: bool = False


class RingEdge(BaseModel):
    from_: str = Field(alias="from")
    to: str

    model_config = {"populate_by_name": True}


class RingGraph(BaseModel):
    nodes: list[RingNode]
    edges: list[RingEdge]


class EvidenceFactor(BaseModel):
    id: str
    label: str
    weight: float
    direction: Direction


class TimelineEvent(BaseModel):
    id: str
    date: str
    title: str
    detail: str | None = None
    kind: Literal["payment", "change", "onboard", "check", "note"] = "note"


class ChecklistItem(BaseModel):
    id: str
    text: str
    done: bool = False


class AuditNote(BaseModel):
    id: str
    at: str
    text: str
    author: str = "Owner"


class PolicyResult(BaseModel):
    """What the Cedar authorization layer lets each principal do with a payment right now."""

    engine: Literal["cedar", "python-mirror"]
    allowed_actions: list[str]
    denied_actions: list[str]
    hold_recommended: bool
    rules_fired: list[str]
    default: str = "deny"
