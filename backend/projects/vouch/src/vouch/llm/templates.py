"""Template writer: plain-English reason and call-back checklist without a model.

Used in ``llm_mode: template`` and as the fallback whenever the live model errors, is
throttled, or writes something that fails the number guard.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import ChecklistItem


@dataclass
class WriterContext:
    vendor_name: str
    amount_text: str
    status: str
    risk: str
    vendor_known: bool
    payments_completed: int
    concerns: list[str] = field(default_factory=list)
    reassuring: list[str] = field(default_factory=list)
    bank_changed: bool = False
    days_since_change: int | None = None
    contact_name: str | None = None
    contact_phone_masked: str | None = None
    duplicate_of_invoice: str | None = None
    split_with_invoices: list[str] = field(default_factory=list)
    combined_text: str | None = None
    approval_limit_text: str = "$5,000"
    shared_bank_with: list[str] = field(default_factory=list)
    shared_phone_with: list[str] = field(default_factory=list)
    new_vendor_verified: bool = False
    invoice_number: str = ""
    sender_flags: list[str] = field(default_factory=list)

    def allowed_numbers(self) -> set[str]:
        """Digit sequences the writer may mention: anything present in the inputs."""
        text = " ".join(
            [
                self.vendor_name,
                self.amount_text,
                self.approval_limit_text,
                self.invoice_number,
                str(self.payments_completed),
            ]
            + self.concerns
            + self.reassuring
            + self.split_with_invoices
            + [self.duplicate_of_invoice or "", self.combined_text or "", self.contact_phone_masked or ""]
            + ([str(self.days_since_change)] if self.days_since_change is not None else [])
        )
        return set(re.findall(r"\d+", text))


def numbers_in(text: str) -> set[str]:
    return set(re.findall(r"\d+", text or ""))


def template_reason(ctx: WriterContext) -> str:
    if ctx.risk == "changed_bank":
        d = ctx.days_since_change
        when = "recently" if d is None else "today" if d == 0 else "1 day ago" if d == 1 else f"{d} days ago"
        extra = (
            " The invoice also arrived from a sender we have not seen before."
            if "lookalike_domain" in ctx.sender_flags or "new_sender_for_known_vendor" in ctx.sender_flags
            else ""
        )
        return f"Bank details changed {when}. A quick call to your usual contact clears this.{extra}"
    if ctx.duplicate_of_invoice:
        return f"Same invoice number and amount as {ctx.duplicate_of_invoice} already in this batch. Likely sent twice."
    if ctx.split_with_invoices:
        return f"One of two invoices just under your {ctx.approval_limit_text} approval limit, sent minutes apart."
    if ctx.shared_bank_with:
        n = len(ctx.shared_bank_with)
        who = "another vendor" if n == 1 else f"{n} other vendors"
        return f"New vendor whose bank account is also used by {who}. Worth a call before paying."
    if ctx.risk == "unrecognized_vendor" and not ctx.vendor_known:
        return "New vendor with no payment history yet. A quick check of the registration and bank name is enough."
    if ctx.status == "quick_check":
        top = ctx.concerns[0].rstrip(".") if ctx.concerns else "One detail needs a look"
        return f"{top}. A quick check clears this; nothing is held automatically."
    if not ctx.vendor_known or ctx.payments_completed == 0:
        if ctx.new_vendor_verified:
            return "New small vendor. Registration, bank name, and invoice all match. Good to pay today."
        return "New vendor; details match and nothing stands out."
    top = ctx.reassuring[0].rstrip(".") if ctx.reassuring else "Everything matches"
    return f"{top}. {'Amount matches the usual order.' if any('usual' in r for r in ctx.reassuring) else 'Everything matches.'}"


def template_checklist(ctx: WriterContext) -> list[ChecklistItem]:
    items: list[str] = []
    if ctx.risk == "changed_bank":
        who = ctx.contact_name or "your usual contact"
        phone = (
            f" at the number on file ({ctx.contact_phone_masked})"
            if ctx.contact_phone_masked
            else " at the number on file"
        )
        items += [
            f"Call {who}{phone}, not the one on the new invoice",
            "Ask them to read the last 4 digits of the new account",
            "Confirm who requested the change and when",
            "If anything is off, keep paying the old account and let us know",
        ]
    elif ctx.duplicate_of_invoice:
        items += [
            f"Check whether {ctx.invoice_number or 'this invoice'} was meant to be sent once",
            "If it was a resend, hold this copy. The first one is ready to pay.",
        ]
    elif ctx.split_with_invoices:
        others = ", ".join(ctx.split_with_invoices)
        items.append(f"Ask {ctx.vendor_name} whether this was one order split in two ({others})")
        if ctx.combined_text:
            items.append(f"If yes, approve both together as a single {ctx.combined_text} payment")
    elif ctx.shared_bank_with or ctx.shared_phone_with:
        items += [
            "Find out who in your team requested this vendor",
            "Call the number from a public listing, not the invoice",
            "Ask for a signed W-9 and proof of the bank account",
        ]
    elif ctx.status != "vouched" and not ctx.vendor_known:
        items += [
            "Confirm the business registration matches the bank account name",
            "Call the vendor on a publicly listed number",
        ]
    elif ctx.status == "quick_check":
        items.append("Confirm the sender with your usual contact before paying")
    return [ChecklistItem(id=f"c{i + 1}", text=t) for i, t in enumerate(items)]
