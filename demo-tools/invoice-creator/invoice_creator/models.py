"""Pydantic models shared by the presets, renderers, mail builder, API and CLI."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

OutputFormat = Literal["pdf", "png", "xlsx", "csv", "body"]
Delivery = Literal["smtp", "receiver_http", "backend", "none"]
AuthVerdict = Literal["pass", "fail", "softfail", "none"]

FORMAT_LABELS: dict[str, str] = {
    "pdf": "PDF attachment",
    "png": "PNG image attachment",
    "xlsx": "Excel (.xlsx) attachment",
    "csv": "CSV attachment",
    "body": "Plain email body (no attachment)",
}


class LineItem(BaseModel):
    description: str
    quantity: float = 1
    unit_price: float = 0.0  # major currency units

    @property
    def amount(self) -> float:
        return round(self.quantity * self.unit_price, 2)


class BankDetails(BaseModel):
    bank_name: str = ""
    account_label: str = "Account Number"  # Account Number | IBAN | CLABE
    account_number: str = ""
    routing_label: str = "Routing Number"  # Routing Number | SWIFT | SWIFT / BIC | Sort Code
    routing_number: str = ""


class RemitTo(BaseModel):
    address: str = ""
    phone: str = ""
    tax_id_label: str = "Tax ID"  # Tax ID | EIN | RFC | NIP | CNPJ
    tax_id: str = ""
    contact_name: str = ""


class Invoice(BaseModel):
    vendor_name: str
    vendor_email: str
    invoice_number: str
    currency: str = "USD"
    amount: float = Field(ge=0)  # total due, major units; the form keeps it in sync with line items
    invoice_date: date
    due_date: date
    po_number: str = ""
    description: str = ""  # one-line summary ("Description: …" on the document)
    line_items: list[LineItem] = Field(default_factory=list)
    bank: BankDetails = Field(default_factory=BankDetails)
    remit_to: RemitTo = Field(default_factory=RemitTo)
    notes: str = ""
    bill_to_name: str = ""  # the business being billed; empty = the operator's configured owner
    bill_to_address: str = ""

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str) -> str:
        return (v or "USD").strip().upper()[:3]

    @property
    def amount_cents(self) -> int:
        return round(self.amount * 100)

    @property
    def line_total(self) -> float:
        return round(sum(li.amount for li in self.line_items), 2)


class AuthSimulation(BaseModel):
    """What the demo tool writes into the Authentication-Results header.

    Real SPF/DKIM/DMARC cannot be forged from a domain we do not control; the header is
    authored by the demo tool and passed through verbatim by the receiver. Labelled as a
    simulation in the UI.
    """

    enabled: bool = True
    spf: AuthVerdict = "pass"
    dkim: AuthVerdict = "pass"
    dmarc: AuthVerdict = "pass"
    dkim_domain: str = ""  # defaults to the From domain


class SenderIdentity(BaseModel):
    from_name: str
    from_addr: str
    reply_to: str = ""
    envelope_from: str = ""  # SMTP MAIL FROM; defaults to from_addr
    subject: str = ""  # defaults to "Invoice <number>"
    body: str = ""  # cover note; the "body" format appends the invoice text
    add_received_header: bool = True  # simulated upstream Received: trace line
    auth: AuthSimulation = Field(default_factory=AuthSimulation)

    @property
    def from_domain(self) -> str:
        return self.from_addr.rsplit("@", 1)[-1].lower() if "@" in self.from_addr else ""


class SendRequest(BaseModel):
    invoice: Invoice
    sender: SenderIdentity
    format: OutputFormat = "pdf"
    delivery: Delivery = "smtp"
    scenario: str = ""  # preset key, for the send log
    label: str = ""  # free text for the send log


class BuiltMessage(BaseModel):
    """What the API returns about a built (not necessarily sent) message."""

    id: str
    message_id: str
    subject: str
    headers: list[list[str]]  # ordered [name, value]
    body_text: str
    attachment_name: str | None = None
    attachment_type: str | None = None
    attachment_size: int = 0
    attachment_sha256: str | None = None
    eml_size: int = 0


class SendLogEntry(BaseModel):
    id: str
    at: str
    scenario: str
    label: str
    vendor_name: str
    invoice_number: str
    amount: float
    currency: str
    format: OutputFormat
    delivery: Delivery
    from_addr: str
    reply_to: str
    to: str
    auth_summary: str
    status: Literal["sent", "failed", "built"]
    detail: str = ""
    message_id: str = ""
    attachment_name: str | None = None
    eml_url: str = ""
    receiver_message_id: str = ""  # set when the receiver acknowledged the message with its id
