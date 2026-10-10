"""Domain models shared by intake, checks, the graph, persistence and the API.

Money is always integer cents parsed in code. The LLM never authors any numeric field:
it may only quote strings from the invoice text (see ``vouch.intake.structure``).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field

VouchStatus = Literal["vouched", "quick_check", "verify"]
Lifecycle = Literal["pending", "approved", "held", "appealed", "settled"]
RiskType = Literal["changed_bank", "duplicate_or_split", "unrecognized_vendor", "none"]
Source = Literal["email", "upload"]
Direction = Literal["concern", "reassuring"]
CountryCode = Literal["US", "MX", "PL", "BR"]


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | date | None) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return dt.isoformat()


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


class InvoiceFields(BaseModel):
    """Strings the structuring step found in the invoice text. Every value MUST be a verbatim
    quote from the source text; non-quoted values are dropped by the provenance check."""

    vendor_name: str | None = None
    vendor_email: str | None = None
    vendor_phone: str | None = None
    vendor_address: str | None = None
    vendor_tax_id: str | None = None
    invoice_number: str | None = None
    po_number: str | None = None
    invoice_date_text: str | None = None
    due_date_text: str | None = None
    total_text: str | None = None
    currency_text: str | None = None
    bank_account_text: str | None = None
    bank_routing_text: str | None = None
    bank_name: str | None = None
    description: str | None = None


class ParsedInvoice(BaseModel):
    """Typed values derived from InvoiceFields by code only."""

    fields: InvoiceFields
    amount_cents: int | None = None
    currency: str = "USD"
    invoice_date: date | None = None
    due_date: date | None = None
    bank_account_digits: str | None = None
    bank_account_last4: str | None = None
    bank_routing_digits: str | None = None
    tax_id_digits: str | None = None
    phone_digits: str | None = None
    email_domain: str | None = None
    parse_warnings: list[str] = Field(default_factory=list)
    provenance_violations: list[str] = Field(default_factory=list)
    structurer: str = "regex"


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


# ------------------------------------------------------------- vendors ----


class BankAccount(BaseModel):
    digits: str
    country: str = "US"
    since: date
    verified_by_callback: bool = True
    requested_by: str | None = None


class PastPayment(BaseModel):
    date: date
    amount_cents: int
    invoice_number: str
    detail: str | None = None


class Vendor(BaseModel):
    id: str
    name: str
    city: str = ""
    country: CountryCode = "US"
    since: date
    payments_completed: int = 0
    history: list[PastPayment] = Field(default_factory=list)
    onboarding_note: str | None = None
    domains: list[str] = Field(default_factory=list)
    tax_id_digits: str | None = None
    phone_digits: str | None = None
    address: str | None = None
    contact_name: str | None = None
    contact_phone_masked: str | None = None
    bank_accounts: list[BankAccount] = Field(default_factory=list)
    typical_amount_cents: int | None = None
    disputes: int = 0
    registration_verified: bool = False
    verified_by_callback: bool = False
    in_queue: bool = True  # False for directory-only vendors (ring members)

    @property
    def current_bank(self) -> BankAccount | None:
        return self.bank_accounts[-1] if self.bank_accounts else None

    @property
    def previous_bank(self) -> BankAccount | None:
        return self.bank_accounts[-2] if len(self.bank_accounts) > 1 else None


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


# ------------------------------------------------------------ findings ----


class BankChangeFindings(BaseModel):
    changed: bool = False
    days_since_change: int | None = None
    requester_verified: bool | None = None
    requested_by: str | None = None
    country_changed: bool = False
    invoice_account_matches_file: bool | None = None
    account_takeover_score: float = 0.0  # 0..1
    flags: list[str] = Field(default_factory=list)


class DupSplitFindings(BaseModel):
    duplicate_of: str | None = None
    split_with: list[str] = Field(default_factory=list)
    minutes_apart: int | None = None
    combined_cents: int | None = None
    under_limit_pattern: bool = False
    flags: list[str] = Field(default_factory=list)


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


class RingFindings(BaseModel):
    shared_bank_with: list[str] = Field(default_factory=list)
    shared_phone_with: list[str] = Field(default_factory=list)
    shared_address_with: list[str] = Field(default_factory=list)
    virtual_office: bool = False
    graph: RingGraph | None = None
    flags: list[str] = Field(default_factory=list)


class EvidenceFactor(BaseModel):
    id: str
    label: str
    weight: float
    direction: Direction
    points: float = 0.0  # signed contribution to the trust score


class PolicyRule(BaseModel):
    id: str
    title: str


class PolicyResult(BaseModel):
    engine: Literal["cedar", "python-mirror"]
    allowed_actions: list[str]
    denied_actions: list[str]
    hold_recommended: bool
    rules_fired: list[str]
    default: str = "deny"


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


class LlmTrace(BaseModel):
    mode: str
    model: str | None = None
    reader_used_llm: bool = False
    writer_used_llm: bool = False
    fallbacks: list[str] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0


class Decision(BaseModel):
    status: VouchStatus
    risk: RiskType
    trust_score: int
    reason: str
    fast_pay_eligible: bool
    evidence: list[EvidenceFactor]
    checklist: list[ChecklistItem]
    policy: PolicyResult
    trace: LlmTrace


class PaymentRecord(BaseModel):
    """What the API serves (snake_case; the frontend normalizes it)."""

    id: str
    vendor_id: str
    vendor_name: str
    vendor_city: str = ""
    vendor_country: CountryCode = "US"
    vendor_since: str
    vendor_payments_completed: int = 0
    invoice_number: str
    amount_cents: int
    currency: str = "USD"
    due_date: str
    invoice_date: str | None = None
    status: VouchStatus
    lifecycle: Lifecycle = "pending"
    risk: RiskType
    trust_score: int
    reason: str
    fast_pay_eligible: bool = False
    source: Source = "email"
    received_at: str
    duplicate_of: str | None = None
    split_with: str | None = None
    evidence: list[EvidenceFactor] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)
    ring: RingGraph | None = None
    audit_notes: list[AuditNote] = Field(default_factory=list)
    policy: PolicyResult | None = None
    sender: SenderFindings | None = None
    vendor_resolution: VendorResolution | None = None
    bank_change: BankChangeFindings | None = None
    dup_split: DupSplitFindings | None = None
    ring_findings: RingFindings | None = None
    parsed: ParsedInvoice | None = None
    trace: LlmTrace | None = None
    run_id: str | None = None
    document_sha256: str | None = None
    bank_account_last4: str | None = None
    settlement_tx_id: str | None = None
    batch_id: str | None = None
    created_at: str = Field(default_factory=lambda: iso(utcnow()) or "")
    updated_at: str = Field(default_factory=lambda: iso(utcnow()) or "")

    def api_view(self) -> dict:
        """Shape consumed by the frontend's ``normalizePayment``."""
        d = self.model_dump(mode="json", by_alias=True)
        d["amount"] = self.amount_cents / 100
        d["vendor"] = {
            "id": self.vendor_id,
            "name": self.vendor_name,
            "city": self.vendor_city,
            "country": self.vendor_country,
            "since": self.vendor_since,
            "payments_completed": self.vendor_payments_completed,
        }
        return d
