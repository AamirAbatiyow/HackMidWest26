"""Deterministic money kernel. Integer cents only; every number a human or LLM sees comes from here.

- `parse_cents`: exact decimal parsing of money strings (US and EU formats) into integer cents.
- `parse_invoice_text`: regex extraction from invoice/PDF text, with the source span kept for each field.
- `check_invoice`: per-invoice deterministic checks against the vendor master and payment history.
- `net_payables` / `batch_totals`: credit-note netting and batch sums.
- `FactSheet`: the closed set of numbers the explainer may mention (see provenance.py).
"""

from __future__ import annotations

import contextlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from vouch.domain import Invoice, Vendor

# --- money ---------------------------------------------------------------------------------------

_MONEY_CHARS = re.compile(r"[^\d.,\-]")
_STRICT_MONEY = re.compile(
    r"^\(?-?\s*(?:[A-Z]{3}\s?)?[$€£]?\s*-?(?:\d{1,3}(?:[,.\s]\d{3})+|\d+)(?:[.,]\d{1,2})?\s*(?:[A-Z]{3})?\)?$"
)


class MoneyParseError(ValueError):
    pass


def parse_cents(text: str | int | Decimal) -> int:
    """'$12,480.00' -> 1248000, '1.234,56' -> 123456, '980' -> 98000. Rejects anything inexact."""
    if isinstance(text, bool):
        raise MoneyParseError("bool is not money")
    if isinstance(text, int):
        return text * 100
    if isinstance(text, Decimal):
        cents = text * 100
        if cents != cents.to_integral_value():
            raise MoneyParseError(f"sub-cent amount: {text}")
        return int(cents)
    if not _STRICT_MONEY.match(str(text).strip()):
        raise MoneyParseError(f"not a well-formed amount: {text!r}")
    raw = _MONEY_CHARS.sub("", str(text).strip())
    negative = raw.startswith("-") or str(text).strip().startswith("(")
    raw = raw.lstrip("-")
    if not raw or not any(ch.isdigit() for ch in raw):
        raise MoneyParseError(f"no amount in {text!r}")
    last_comma, last_dot = raw.rfind(","), raw.rfind(".")
    if last_comma > last_dot and len(raw) - last_comma - 1 == 2:
        raw = raw.replace(".", "").replace(",", ".")  # EU: 1.234,56
    else:
        raw = raw.replace(",", "")
    if raw.count(".") > 1:
        raise MoneyParseError(f"ambiguous amount {text!r}")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise MoneyParseError(f"bad amount {text!r}") from exc
    cents = value * 100
    if cents != cents.to_integral_value():
        raise MoneyParseError(f"sub-cent amount: {text!r}")
    return -int(cents) if negative else int(cents)


def format_cents(cents: int, currency: str = "USD") -> str:
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    symbol = "$" if currency == "USD" else f"{currency} "
    return f"{sign}{symbol}{whole:,}.{frac:02d}"


# --- text parsing --------------------------------------------------------------------------------

_DATE_PATTERNS = [
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), lambda m: date(int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})"), lambda m: date(int(m[3]), int(m[1]), int(m[2]))),
]
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1
    )
}
_TEXT_DATE = re.compile(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})")

_FIELD_PATTERNS: dict[str, re.Pattern[str]] = {
    "invoice_number": re.compile(
        r"invoice\s*(?:no\.?|number|#|:)\s*[:#]?\s*([A-Z0-9\-/]*\d[A-Z0-9\-/]*)", re.I
    ),
    "po_number": re.compile(
        r"\b(?:p\.?o\.?|purchase\s+order)\s*(?:no\.?|number|#)?\s*[:#]?\s*([A-Z0-9\-]*\d[A-Z0-9\-]*)", re.I
    ),
    "amount_text": re.compile(
        r"\b(?:total\s+due|amount\s+due|balance\s+due|invoice\s+total|total)\s*(?:\(?[A-Z]{3}\)?)?\s*[:=]?\s*"
        r"((?:[A-Z]{3}\s*)?[$€£]?\s*-?\d[\d,.]*\d)(?!\w)",
        re.I,
    ),
    "due_date": re.compile(
        r"(?:due\s+date|payment\s+due(?:\s+date)?|due\s+(?:on|by))\s*[:=]?\s*([^\n]{6,24})", re.I
    ),
    "issue_date": re.compile(
        r"(?:invoice\s+date|issue\s+date|date\s+issued|(?<!due\s)\bdate)\s*[:=]\s*([^\n]{6,24})", re.I
    ),
    "bank_account": re.compile(
        r"(?:iban|account\s*(?:no\.?|number|#)?|acct\.?)\s*[:#]?\s*([A-Z]{2}\d{2}[A-Z0-9 ]{8,30}|[\d\- ]{6,20}\d)",
        re.I,
    ),
    "remit_email": re.compile(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"),
    "vendor_name": re.compile(r"(?:from|vendor|bill\s+from|remit\s+to)\s*[:\-]\s*([^\n]{3,60})", re.I),
    "currency": re.compile(r"\b(USD|EUR|MXN|VND|INR|GBP|CAD)\b"),
}


def parse_date(text: str) -> date | None:
    for pattern, build in _DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            try:
                return build(m)
            except ValueError:
                return None
    m = _TEXT_DATE.search(text)
    if m and m[1].lower()[:3] in _MONTHS:
        try:
            return date(int(m[3]), _MONTHS[m[1].lower()[:3]], int(m[2]))
        except ValueError:
            return None
    return None


def normalize_account(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"[^A-Z0-9]", "", value.upper()) or None


@dataclass
class ParsedText:
    fields: dict[str, Any] = field(default_factory=dict)
    spans: dict[str, str] = field(default_factory=dict)  # field -> exact source substring
    missing: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing


REQUIRED_TEXT_FIELDS = ("vendor_name", "invoice_number", "amount_cents", "due_date")


def parse_invoice_text(text: str) -> ParsedText:
    """Best-effort deterministic extraction. Fields it cannot find are listed in `missing`."""
    out = ParsedText()
    for name, pattern in _FIELD_PATTERNS.items():
        m = pattern.search(text)
        if m:
            out.spans[name] = m.group(1).strip()
    if "amount_text" in out.spans:
        with contextlib.suppress(MoneyParseError):
            out.fields["amount_cents"] = parse_cents(out.spans["amount_text"])
    for key in ("due_date", "issue_date"):
        if key in out.spans and (d := parse_date(out.spans[key])):
            out.fields[key] = d
    for key in ("invoice_number", "po_number", "remit_email", "vendor_name", "currency"):
        if key in out.spans:
            out.fields[key] = out.spans[key].strip(" .,")
    if "bank_account" in out.spans:
        out.fields["bank_account"] = normalize_account(out.spans["bank_account"])
    out.missing = [f for f in REQUIRED_TEXT_FIELDS if f not in out.fields]
    return out


# --- adversarial text ----------------------------------------------------------------------------

_INJECTION = [
    r"ignore (?:all |any )?(?:previous|prior|above) (?:instructions|rules)",
    r"\b(?:system|assistant|ai|agent|model)\s*(?:prompt|note|instruction)?\s*:",
    r"(?:you are|act as) (?:now )?(?:an?|the) ",
    r"(?:do not|don't|never) (?:hold|flag|review|escalate|verify)",
    r"(?:skip|bypass|override) (?:the )?(?:approval|review|policy|verification|owner)",
    r"(?:pre-?approved|already approved|auto-?approve|approved by (?:the )?(?:owner|ceo|cfo))",
    r"(?:release|send|wire) (?:the )?(?:payment|funds) (?:immediately|now|today)",
    r"(?:update|change|use) (?:the )?(?:bank|account|wallet|remit)\w* (?:details|number|to)",
    r"(?:set|change) (?:the )?amount to",
]
_INJECTION_RE = re.compile("|".join(_INJECTION), re.I)
_URGENCY_RE = re.compile(
    r"\b(urgent|urgently|immediately|asap|today|overdue|final notice|right away|confidential|time.sensitive)\b",
    re.I,
)


def injection_signals(text: str) -> list[str]:
    return sorted({m.group(0).strip().lower() for m in _INJECTION_RE.finditer(text or "")})


def urgency_terms(text: str) -> int:
    return len(_URGENCY_RE.findall(text or ""))


# --- per-invoice checks ---------------------------------------------------------------------------


@dataclass
class Limits:
    approval_limit_cents: int = 500_000  # clerk approval limit; splits hide under it
    fast_pay_limit_cents: int = 250_000
    single_payment_limit_cents: int = 5_000_000
    batch_limit_cents: int = 10_000_000
    bank_change_window_days: int = 90
    split_window_days: int = 7
    duplicate_window_days: int = 60


def _norm_invoice_number(num: str) -> str:
    core = re.sub(r"[^A-Z0-9]", "", num.upper())
    return re.sub(r"(?<=\d)[A-Z]{1,2}$", "", core)  # INV-2291A == INV2291


# Owner-facing names for the vendor attributes the ring graph compares (VendorGraph.ATTRIBUTES).
_SHARED_LABELS = {
    "bank": "bank account",
    "tax_id": "tax ID",
    "phone": "phone number",
    "address": "address",
    "email_domain": "email domain",
}


@dataclass
class InvoiceChecks:
    vendor_found: bool
    line_items_match: bool
    bank_mismatch: bool  # invoice bank details differ from vendor master
    bank_change_recent: bool  # master record changed inside the window
    bank_change_confirmed: bool
    contact_change_recent: bool
    remit_email_mismatch: bool
    duplicate_of: str | None
    split_group: list[str]
    split_total_cents: int
    over_approval_limit: bool
    over_single_limit: bool
    near_approval_limit: bool
    no_po: bool
    no_delivery: bool
    history_count: int
    history_median_cents: int
    amount_ratio_milli: int  # amount / median history * 1000 (integer)
    creep_milli: int  # growth of last 3 payments vs first 3, * 1000
    urgency_terms: int
    injection: list[str]
    amount_origin_ok: bool
    shared_attributes: dict[str, list[str]] = field(default_factory=dict)

    @property
    def bank_unconfirmed(self) -> bool:
        return self.bank_mismatch or (self.bank_change_recent and not self.bank_change_confirmed)

    def flags(self) -> list[str]:
        out = []
        if not self.vendor_found:
            out.append("vendor is not in your vendor list")
        if self.bank_mismatch:
            out.append("bank account on the invoice differs from the one on file")
        if self.bank_change_recent and not self.bank_change_confirmed:
            out.append("bank account changed recently and was not confirmed by phone")
        if self.contact_change_recent:
            out.append("vendor contact details changed recently")
        if self.remit_email_mismatch:
            out.append("payment email differs from the vendor email on file")
        if self.duplicate_of:
            out.append(f"possible duplicate of {self.duplicate_of}")
        if self.split_group:
            out.append("looks like one bill split into invoices just under the approval limit")
        if self.over_single_limit:
            out.append("amount is over the single-payment limit")
        if self.no_po and self.no_delivery:
            out.append("no purchase order and no delivery confirmation")
        if not self.line_items_match:
            out.append("line items do not add up to the invoice total")
        if self.injection:
            out.append("invoice text tries to give orders to the payment system")
        if not self.amount_origin_ok:
            out.append("amount could not be read from the invoice")
        for kind, others in self.shared_attributes.items():
            n = len(others)
            label = _SHARED_LABELS.get(kind, kind.replace("_", " "))
            out.append(f"shares the same {label} with {n} other vendor{'s' if n != 1 else ''}")
        return out


def _median(values: list[int]) -> int:
    if not values:
        return 0
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) // 2


def _domain(email: str | None) -> str | None:
    return email.rsplit("@", 1)[-1].lower() if email and "@" in email else None


def check_invoice(
    inv: Invoice,
    vendor: Vendor | None,
    batch: list[Invoice],
    limits: Limits,
    today: date,
    shared_attributes: dict[str, list[str]] | None = None,
) -> InvoiceChecks:
    history = vendor.history if vendor else []
    amounts = [p.amount_cents for p in history]
    median = _median(amounts)
    line_ok = not inv.line_items or sum(li.total_cents for li in inv.line_items) == inv.amount_cents
    inv_bank = normalize_account(inv.bank_account)
    master_bank = normalize_account(vendor.bank_account) if vendor else None
    bank_mismatch = bool(vendor and inv_bank and inv_bank != master_bank)
    bank_recent = bool(
        vendor
        and vendor.bank_changed_days_ago is not None
        and vendor.bank_changed_days_ago <= limits.bank_change_window_days
    )
    contact_recent = bool(
        vendor and vendor.contact_changed_days_ago is not None and vendor.contact_changed_days_ago <= 30
    )
    remit_mismatch = bool(vendor and inv.remit_email and _domain(inv.remit_email) != _domain(vendor.email))

    # Duplicates: same normalized number, or same amount to the same vendor recently (history or batch).
    duplicate_of = None
    norm = _norm_invoice_number(inv.invoice_number)
    for past in history:
        if past.invoice_number and _norm_invoice_number(past.invoice_number) == norm:
            duplicate_of = f"paid invoice {past.invoice_number} ({past.days_ago} days ago)"
            break
        if past.amount_cents == inv.amount_cents and past.days_ago <= limits.duplicate_window_days:
            duplicate_of = f"payment of {format_cents(past.amount_cents)} {past.days_ago} days ago"
            break
    if duplicate_of is None:
        for other in batch:
            if other.id == inv.id or other.vendor_id != inv.vendor_id or other.is_credit_note:
                continue
            same = (
                _norm_invoice_number(other.invoice_number) == norm or other.amount_cents == inv.amount_cents
            )
            if same and other.id < inv.id:  # flag the later one only
                duplicate_of = f"invoice {other.invoice_number} in this batch"
                break

    # Splits: several invoices from one vendor within a few days, each just under the approval limit
    # (>= 70% of it), together over it, and outside the PO process (which is what splitting dodges).
    split_group: list[str] = []
    split_total = 0
    floor = limits.approval_limit_cents * 7 // 10

    def _near(cents: int) -> bool:
        return floor <= cents < limits.approval_limit_cents

    if _near(inv.amount_cents) and not inv.is_credit_note and not inv.po_number:
        siblings = [
            o
            for o in batch
            if o.vendor_id == inv.vendor_id
            and not o.is_credit_note
            and _near(o.amount_cents)
            and abs((o.issue_date - inv.issue_date).days) <= limits.split_window_days
        ]
        recent = [
            p.amount_cents
            for p in history
            if p.days_ago <= limits.split_window_days and _near(p.amount_cents)
        ]
        total = sum(o.amount_cents for o in siblings) + sum(recent)
        if len(siblings) + len(recent) >= 2 and total > limits.approval_limit_cents:
            split_group = sorted(o.id for o in siblings)
            split_total = total

    ordered = [p.amount_cents for p in sorted(history, key=lambda p: -p.days_ago)]
    creep = 0
    if len(ordered) >= 6:
        first, last = sum(ordered[:3]), sum(ordered[-3:])
        creep = (last - first) * 1000 // max(first, 1)

    return InvoiceChecks(
        vendor_found=vendor is not None,
        line_items_match=line_ok,
        bank_mismatch=bank_mismatch,
        bank_change_recent=bank_recent,
        bank_change_confirmed=bool(vendor and vendor.bank_change_confirmed_oob),
        contact_change_recent=contact_recent,
        remit_email_mismatch=remit_mismatch,
        duplicate_of=duplicate_of,
        split_group=split_group,
        split_total_cents=split_total,
        over_approval_limit=inv.amount_cents > limits.approval_limit_cents,
        over_single_limit=inv.amount_cents > limits.single_payment_limit_cents,
        near_approval_limit=limits.approval_limit_cents * 9 // 10
        <= inv.amount_cents
        < limits.approval_limit_cents,
        no_po=not inv.po_number,
        no_delivery=not inv.delivery_confirmed,
        history_count=len(history),
        history_median_cents=median,
        amount_ratio_milli=inv.amount_cents * 1000 // median if median else 0,
        creep_milli=creep,
        urgency_terms=urgency_terms(inv.raw_text),
        injection=injection_signals(inv.raw_text),
        amount_origin_ok=inv.amount_origin in ("source", "kernel"),
        shared_attributes=shared_attributes or {},
    )


# --- netting & totals -----------------------------------------------------------------------------


def net_payables(invoices: list[Invoice]) -> dict[str, dict[str, int]]:
    """Per vendor: gross invoices, credit notes, net payable (never negative; leftover credit carries)."""
    out: dict[str, dict[str, int]] = defaultdict(lambda: {"gross_cents": 0, "credits_cents": 0})
    for inv in invoices:
        key = inv.vendor_id or inv.vendor_name
        bucket = "credits_cents" if inv.is_credit_note else "gross_cents"
        out[key][bucket] += abs(inv.amount_cents)
    result = {}
    for key, v in out.items():
        net = v["gross_cents"] - v["credits_cents"]
        result[key] = {**v, "net_cents": max(net, 0), "carry_credit_cents": max(-net, 0)}
    return result


def allocate_credits(invoices: list[Invoice]) -> dict[str, int]:
    """Payable cents per invoice id after applying each vendor's credit notes to its oldest invoices."""
    credits: dict[str, int] = defaultdict(int)
    for inv in invoices:
        if inv.is_credit_note:
            credits[inv.vendor_id or inv.vendor_name] += abs(inv.amount_cents)
    payable: dict[str, int] = {}
    for inv in sorted((i for i in invoices if not i.is_credit_note), key=lambda i: (i.due_date, i.id)):
        key = inv.vendor_id or inv.vendor_name
        applied = min(credits[key], inv.amount_cents)
        credits[key] -= applied
        payable[inv.id] = inv.amount_cents - applied
    return payable


def batch_totals(items: list[tuple[str, str, int]]) -> dict[str, Any]:
    """items: (vendor_id, currency, cents). Exact integer sums per currency and per vendor."""
    by_currency: dict[str, int] = defaultdict(int)
    by_vendor: dict[str, int] = defaultdict(int)
    for vendor_id, currency, cents in items:
        by_currency[currency] += cents
        by_vendor[vendor_id] += cents
    return {
        "count": len(items),
        "total_cents": sum(c for _, _, c in items),
        "by_currency_cents": dict(by_currency),
        "by_vendor_cents": dict(by_vendor),
    }


def days_until(d: date, today: date) -> int:
    return (d - today).days


def add_days(d: date, n: int) -> date:
    return d + timedelta(days=n)


# --- facts ----------------------------------------------------------------------------------------


@dataclass
class FactSheet:
    """Closed set of facts for one payment card. LLM text may only cite values in here."""

    values: dict[str, str] = field(default_factory=dict)

    def add(self, key: str, value: Any) -> None:
        if isinstance(value, float):
            value = f"{value:.2f}"
        self.values[key] = str(value)

    def add_cents(self, key: str, cents: int, currency: str = "USD") -> None:
        self.values[key] = format_cents(cents, currency)

    def add_percent(self, key: str, prob: float) -> None:
        self.values[key] = f"{round(prob * 100)}%"

    def as_prompt(self) -> str:
        return "\n".join(f"- {k}: {v}" for k, v in sorted(self.values.items()))
