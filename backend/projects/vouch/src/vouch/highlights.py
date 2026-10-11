"""Highlighted-invoice view: the invoice rendered as a list of document fields, each tagged with a
severity and short reasons so the frontend can paint suspicious fields red with an inline tag.

Everything here is derived from facts the engine already computed: the kernel's `InvoiceChecks`
(`card.checks`), the numeric features that feed VouchNet/LIME (`card.features`), the deterministic
sender check and the vendor resolution. Nothing is re-scored and no LLM is involved; a field with
`severity == "ok"` simply has no finding against it.

Severity: `high` (red: drove or would drive a hold), `warn` (amber: worth a glance), `ok` (neutral).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from vouch.cards import PaymentCard
from vouch.domain import Lane, Vendor
from vouch.kernel import format_cents

Severity = Literal["ok", "warn", "high"]
_RANK: dict[Severity, int] = {"ok": 0, "warn": 1, "high": 2}
_IBAN_COUNTRY = re.compile(r"^([A-Z]{2})\d{2}")

FIELD_LABELS = {
    "vendor_name": "Vendor",
    "invoice_number": "Invoice no.",
    "issue_date": "Invoice date",
    "due_date": "Due date",
    "po_number": "Purchase order",
    "amount": "Amount due",
    "bank_account": "Bank account",
    "tax_id": "Tax ID",
    "address": "Address",
    "phone": "Phone",
    "sender_email": "Sender",
    "reply_to": "Reply-To",
    "remit_email": "Remit email",
    "message": "Email text",
}


class _Field:
    def __init__(self, field: str, value: str) -> None:
        self.field = field
        self.value = value
        self.severity: Severity = "ok"
        self.reasons: list[str] = []

    def flag(self, severity: Severity, reason: str) -> None:
        if _RANK[severity] > _RANK[self.severity]:
            self.severity = severity
        if reason not in self.reasons:
            self.reasons.append(reason)

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "label": FIELD_LABELS.get(self.field, self.field.replace("_", " ").capitalize()),
            "value": self.value,
            "severity": self.severity,
            "reason": " · ".join(self.reasons) if self.reasons else None,
            "reasons": list(self.reasons),
        }


def _plural(n: int, noun: str) -> str:
    return f"{n} other {noun}" if n == 1 else f"{n} other {noun}s"


def _names(ids: list[str], vendors: dict[str, Vendor]) -> str:
    names = [vendors[v].name for v in ids if v in vendors]
    return f" ({', '.join(names)})" if names else ""


def _shared(field: _Field, kind: str, shared: dict[str, list[str]], vendors: dict[str, Vendor]) -> None:
    others = shared.get(kind) or []
    if others:
        noun = {"bank": "bank account", "tax_id": "tax ID", "phone": "phone number", "address": "address"}
        field.flag(
            "high",
            f"{noun.get(kind, kind)} shared with {_plural(len(others), 'vendor')}{_names(others, vendors)}",
        )


def _account_country(account: str | None) -> str | None:
    m = _IBAN_COUNTRY.match((account or "").upper())
    return m.group(1) if m else None


def _feature_on(card: PaymentCard, name: str) -> bool:
    return float(card.features.get(name, 0.0)) >= 0.5


def highlights_of(card: PaymentCard, vendors: dict[str, Vendor]) -> list[dict[str, Any]]:
    inv = card.invoice
    vendor = card.vendor
    ch = card.checks or {}
    shared: dict[str, list[str]] = ch.get("shared_attributes") or {}
    hold = bool(card.policy and card.policy.lane == Lane.HOLD)
    out: list[_Field] = []

    # -- vendor ------------------------------------------------------------------------------------
    name = _Field("vendor_name", inv.vendor_name)
    status = card.resolution.status if card.resolution else ("known" if vendor else "new")
    if status == "new" or not ch.get("vendor_found", vendor is not None):
        name.flag("high", "not on the vendor master file")
    elif status == "uncertain":
        name.flag("warn", "fuzzy name match only")
    if vendor and vendor.created_days_ago <= 60 and not vendor.history:
        name.flag("warn", f"vendor added {vendor.created_days_ago} days ago, no payments yet")
    out.append(name)

    # -- invoice number / dates / PO -----------------------------------------------------------------
    number = _Field("invoice_number", inv.invoice_number)
    if ch.get("duplicate_of"):
        number.flag("high", f"possible duplicate of {ch['duplicate_of']}")
    if ch.get("split_group"):
        number.flag("high", "possible split invoice under the approval limit")
    out.append(number)

    out.append(_Field("issue_date", inv.issue_date.isoformat()))
    due = _Field("due_date", inv.due_date.isoformat())
    urgency = int(ch.get("urgency_terms") or 0)
    if urgency:
        due.flag("warn", f"urgency language ({urgency} term{'s' if urgency != 1 else ''})")
    out.append(due)

    po = _Field("po_number", inv.po_number or "none")
    if ch.get("no_po") and ch.get("no_delivery"):
        po.flag("warn", "no purchase order and no delivery confirmation")
    out.append(po)

    # -- amount ------------------------------------------------------------------------------------
    amount = _Field("amount", format_cents(inv.amount_cents, inv.currency))
    if ch.get("amount_origin_ok") is False:
        amount.flag("high", "amount was not produced by the deterministic kernel")
    if ch.get("over_single_limit"):
        amount.flag("high", "exceeds the single-payment limit")
    if ch.get("split_group"):
        amount.flag("high", "just under the approval limit · part of a split")
    elif ch.get("near_approval_limit"):
        amount.flag("warn", "just under the approval limit")
    if ch.get("line_items_match") is False:
        amount.flag("high", "line items don't add up to the total")
    if _feature_on(card, "round_amount"):
        amount.flag("high" if hold else "warn", "round-thousand amount")
    ratio = int(ch.get("amount_ratio_milli") or 0)
    if ch.get("history_count") and ratio >= 2000:
        amount.flag("warn", f"{ratio / 1000:.1f}× this vendor's usual amount")
    out.append(amount)

    # -- bank account ------------------------------------------------------------------------------
    account_value = inv.bank_account or (vendor.bank_account if vendor else None)
    if account_value:
        bank = _Field("bank_account", account_value)
        if ch.get("bank_mismatch") and vendor:
            bank.flag("high", f"differs from the account on file (···{vendor.bank_account[-4:]})")
        if ch.get("bank_change_recent") and not ch.get("bank_change_confirmed") and vendor:
            bank.flag(
                "high",
                f"changed {vendor.bank_changed_days_ago} days ago without call-back confirmation",
            )
        _shared(bank, "bank", shared, vendors)
        country = _account_country(inv.bank_account)
        if vendor and country and country != vendor.country:
            bank.flag("warn", f"account in {country}, vendor in {vendor.country}")
        out.append(bank)

    # -- vendor master identity ----------------------------------------------------------------------
    if vendor:
        tax = _Field("tax_id", vendor.tax_id)
        if _feature_on(card, "tax_id_invalid"):
            tax.flag("high", "tax ID fails checksum")
        _shared(tax, "tax_id", shared, vendors)
        out.append(tax)

        address = _Field("address", vendor.address)
        if _feature_on(card, "address_virtual"):
            address.flag("high", "virtual office / PO box address")
        _shared(address, "address", shared, vendors)
        out.append(address)

        phone = _Field("phone", vendor.phone)
        if _feature_on(card, "phone_voip"):
            phone.flag("high", "VOIP / toll-free number")
        _shared(phone, "phone", shared, vendors)
        out.append(phone)

    # -- email envelope ------------------------------------------------------------------------------
    sender = card.sender
    if sender and sender.checked:
        flags = set(sender.flags)
        who = _Field("sender_email", sender.from_addr or sender.from_domain)
        if "lookalike_domain" in flags:
            closest = sender.lookalike.closest_known_domain if sender.lookalike else None
            who.flag("high", f"lookalike of {closest}" if closest else "lookalike sender domain")
        if flags & {"spf_fail", "dkim_fail", "dmarc_fail"}:
            failed = [k.upper() for k in ("spf", "dkim", "dmarc") if f"{k}_fail" in flags]
            who.flag("high", f"failed {'/'.join(failed)} authentication")
        elif flags & {"spf_softfail", "dkim_missing", "no_authentication_results"}:
            who.flag("warn", "weak email authentication")
        if "new_sender_for_known_vendor" in flags:
            who.flag("warn", "address never used by this vendor before")
        if "display_name_mismatch" in flags:
            who.flag("warn", "display name doesn't match the domain")
        if "freemail_sender" in flags:
            who.flag("warn", "free webmail provider")
        out.append(who)

        if sender.reply_to:
            reply = _Field("reply_to", sender.reply_to)
            if "reply_to_lookalike_domain" in flags:
                reply.flag("high", "lookalike domain")
            if sender.reply_to_mismatch or "reply_to_mismatch" in flags:
                reply.flag("high", "reply-to differs from sender")
            out.append(reply)
    else:
        out.append(_Field("sender_email", f"uploaded by {inv.submitted_by} · no email envelope"))

    if inv.remit_email:
        remit = _Field("remit_email", inv.remit_email)
        if ch.get("remit_email_mismatch") and vendor:
            remit.flag(
                "high", f"domain differs from vendor email on file (@{vendor.email.rsplit('@', 1)[-1]})"
            )
        out.append(remit)

    injection: list[str] = ch.get("injection") or []
    if injection:
        text = _Field("message", "; ".join(f"“{s}”" for s in injection[:3]))
        text.flag("high", "instructions aimed at the payment system")
        out.append(text)

    return [f.as_dict() for f in out]
