"""Turn extracted invoice text into typed fields.

Two structurers produce ``InvoiceFields`` (strings only):

* ``regex_structure`` — deterministic label matching; always available; template-mode default.
* the LLM reader (``vouch.llm.reader``) — Pydantic structured output from the Akamai chat model.

Both go through ``provenance_check``: any value that is not a verbatim quote of the source
text is dropped and recorded. ``parse_fields`` then derives money, dates and identifiers in
code. Instructions embedded in the invoice are therefore data, never commands.
"""

from __future__ import annotations

import re

from ..models import InvoiceFields, ParsedInvoice
from .amounts import (
    AmountParseError,
    detect_currency,
    digits_only,
    email_domain,
    normalize_account,
    parse_amount_cents,
    parse_date,
)

_LABELS: dict[str, list[str]] = {
    "invoice_number": [
        r"invoice\s*(?:no|number|#|nr|№)\.?",
        r"invoice\s*id",
        r"inv\.?\s*(?:no|#)",
        r"factura\s*(?:no|#)?",
        r"faktura\s*(?:nr|vat)?",
    ],
    "po_number": [r"p\.?o\.?\s*(?:no|number|#)?", r"purchase\s*order\s*(?:no|#)?", r"order\s*ref(?:erence)?"],
    "total_text": [
        r"total\s*due",
        r"amount\s*due",
        r"balance\s*due",
        r"grand\s*total",
        r"total\s*amount",
        r"invoice\s*total",
        r"total",
    ],
    "due_date_text": [r"due\s*date", r"payment\s*due", r"due\s*(?:on|by)", r"due"],
    "invoice_date_text": [r"invoice\s*date", r"date\s*of\s*issue", r"issued?(?:\s*on)?", r"date"],
    "bank_account_text": [
        r"iban",
        r"account\s*(?:no|number|#)",
        r"acct\.?\s*(?:no|#)?",
        r"clabe",
        r"beneficiary\s*account",
        r"bank\s*account",
    ],
    "bank_routing_text": [
        r"routing\s*(?:no|number|#)?",
        r"aba",
        r"swift(?:\s*/\s*bic)?",
        r"bic",
        r"sort\s*code",
    ],
    "bank_name": [r"bank\s*name", r"bank(?!\s*account)"],
    "vendor_tax_id": [r"tax\s*id", r"ein", r"vat\s*(?:no|id|number)?", r"nip", r"cnpj", r"rfc", r"tin"],
    "vendor_email": [r"e-?mail"],
    "vendor_phone": [r"phone", r"tel(?:ephone)?", r"mobile"],
    "vendor_address": [r"address", r"remit\s*to", r"bill\s*from"],
    "description": [r"description", r"for", r"service", r"item"],
}

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_MONEY_RE = re.compile(
    r"(?:US\$|MX\$|R\$|\$|€|£|zł|USD|MXN|PLN|BRL|EUR)\s?\d[\d.,\s]*\d|\d[\d.,]*\d\s?(?:USD|MXN|PLN|BRL|EUR|zł)"
)
_COMPANY_RE = re.compile(
    r"(?i)\b(inc|llc|ltd|co|corp|company|gmbh|s\.?a\.?|sp\.? z o\.?o\.?|ltda|plc|packaging|supply|supplies|steel|pallets|"
    r"freight|trade|trading|logistics|services|caf[eé]|consulting|industries|manufacturing|group)\b\.?"
)
_GREETING_RE = re.compile(
    r"(?i)^(dear|hello|hi|hola|good (morning|afternoon)|to whom|please|kind regards|regards|thanks|thank you|attached|note)"
)
_SEPARATOR_RE = re.compile(r"^\s*(\[\[|===|---)")
_NEXT_LABEL_RE = re.compile(r"\s{2,}|\s+(?=[A-Z][A-Za-z .]{1,24}:\s)|\s+\|\s+")


def _clean_value(value: str) -> str:
    return _NEXT_LABEL_RE.split(value.strip(), maxsplit=1)[0].strip(" |")


def _find_label(text: str, patterns: list[str]) -> str | None:
    lines = [ln for ln in text.splitlines() if not _SEPARATOR_RE.match(ln)]
    body = "\n".join(lines)
    for pat in patterns:
        m = re.search(rf"(?im)^\W*{pat}\s*[:#\-]?\s*(?P<v>.+?)\s*$", body)
        if m and m.group("v").strip():
            value = _clean_value(m.group("v"))
            if value:
                return value
        m = re.search(rf"(?i)\b{pat}\s*[:#]\s*(?P<v>[^\n|]+)", body)
        if m and m.group("v").strip():
            value = _clean_value(m.group("v"))
            if value:
                return value
    return None


def _guess_vendor_name(text: str) -> str | None:
    candidates: list[str] = []
    for ln in text.splitlines():
        s = ln.strip().strip("|").strip()
        if not s or _SEPARATOR_RE.match(ln) or "@" in s or len(s) > 70 or _GREETING_RE.match(s):
            continue
        if re.match(r"(?i)^(invoice|factura|faktura|tax invoice|bill|statement)\b", s) or ":" in s:
            continue
        if sum(ch.isdigit() for ch in s) > len(s) / 3:
            continue
        candidates.append(s)
    for s in candidates:
        if _COMPANY_RE.search(s):
            return s
    return candidates[0] if candidates else None


def regex_structure(text: str) -> InvoiceFields:
    """Label-driven extraction of candidate strings from normalized text."""
    fields = InvoiceFields()
    for name, patterns in _LABELS.items():
        value = _find_label(text, patterns)
        if value:
            setattr(fields, name, value)
    if fields.vendor_email:
        m = _EMAIL_RE.search(fields.vendor_email)
        fields.vendor_email = m.group(0) if m else None
    if not fields.vendor_email:
        m = _EMAIL_RE.search(text)
        if m:
            fields.vendor_email = m.group(0)
    if fields.vendor_phone:
        fields.vendor_phone = re.split(r"\s+(?=[A-Za-z])", fields.vendor_phone, maxsplit=1)[0]
    # Vendor name: an explicit label, else the first line that looks like a company.
    labelled = _find_label(text, [r"vendor", r"supplier", r"seller", r"company", r"bill from", r"remit to"])
    if labelled and len(labelled) < 80 and "@" not in labelled and not _GREETING_RE.match(labelled):
        fields.vendor_name = labelled
    else:
        fields.vendor_name = _guess_vendor_name(text)
    if (
        fields.total_text
        and not _MONEY_RE.search(fields.total_text)
        and not re.search(r"\d", fields.total_text)
    ):
        fields.total_text = None
    if not fields.total_text:
        # Prefer a "total" line; otherwise the largest money mention.
        best = None
        for m in _MONEY_RE.finditer(text):
            try:
                cents = parse_amount_cents(m.group(0))
            except AmountParseError:
                continue
            if best is None or cents > best[0]:
                best = (cents, m.group(0))
        if best:
            fields.total_text = best[1]
    if fields.currency_text is None and fields.total_text:
        m = re.search(r"\b(USD|MXN|PLN|BRL|EUR|GBP)\b", text)
        if m:
            fields.currency_text = m.group(1)
    return fields


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def provenance_check(fields: InvoiceFields, text: str) -> tuple[InvoiceFields, list[str]]:
    """Drop every value that is not a verbatim (whitespace/case-insensitive) quote of the text."""
    haystack = _norm(text)
    violations: list[str] = []
    kept = fields.model_copy()
    for name, value in fields.model_dump().items():
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip() or _norm(value) not in haystack:
            violations.append(f"{name}={value!r} is not quoted from the invoice; dropped")
            setattr(kept, name, None)
    return kept, violations


def parse_fields(fields: InvoiceFields, text: str, structurer: str = "regex") -> ParsedInvoice:
    """Derive typed values from quoted strings. Numbers and dates come only from this code."""
    checked, violations = provenance_check(fields, text)
    parsed = ParsedInvoice(fields=checked, structurer=structurer, provenance_violations=violations)
    warnings = parsed.parse_warnings
    if checked.total_text:
        try:
            parsed.amount_cents = parse_amount_cents(checked.total_text)
        except AmountParseError as exc:
            warnings.append(str(exc))
    if parsed.amount_cents is None:
        fallback = regex_structure(text).total_text
        if fallback:
            try:
                parsed.amount_cents = parse_amount_cents(fallback)
                checked.total_text = fallback
                warnings.append("total taken from deterministic scan of the text")
            except AmountParseError as exc:
                warnings.append(str(exc))
    parsed.currency = detect_currency((checked.currency_text or "") + " " + (checked.total_text or ""), "USD")
    parsed.due_date = parse_date(checked.due_date_text)
    parsed.invoice_date = parse_date(checked.invoice_date_text)
    if checked.due_date_text and parsed.due_date is None:
        warnings.append(f"could not parse due date {checked.due_date_text!r}")
    parsed.bank_account_digits = normalize_account(checked.bank_account_text)
    if parsed.bank_account_digits:
        parsed.bank_account_last4 = parsed.bank_account_digits[-4:]
    parsed.bank_routing_digits = normalize_account(checked.bank_routing_text)
    parsed.tax_id_digits = digits_only(checked.vendor_tax_id)
    parsed.phone_digits = digits_only(checked.vendor_phone)
    parsed.email_domain = email_domain(checked.vendor_email)
    return parsed


def mask_account(digits: str | None) -> str:
    if not digits:
        return "unknown"
    return f"···{digits[-4:]}"
