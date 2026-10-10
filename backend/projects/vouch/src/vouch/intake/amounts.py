"""Strict, deterministic parsers for money, dates and identifiers.

These are the only places where numbers on an invoice become typed values. They never
round, never guess between ambiguous readings (ambiguity is reported, not resolved) and
are covered by tests.
"""

from __future__ import annotations

import re
from datetime import date, datetime

CURRENCY_SYMBOLS = {"$": "USD", "US$": "USD", "R$": "BRL", "zł": "PLN", "€": "EUR", "£": "GBP", "MX$": "MXN"}
CURRENCY_CODES = {"USD", "MXN", "PLN", "BRL", "EUR", "GBP", "CAD"}

_NUM_RE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[.,\s\u00a0]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?![\d])"
)


class AmountParseError(ValueError):
    pass


def detect_currency(text: str, default: str = "USD") -> str:
    t = text.strip()
    for code in CURRENCY_CODES:
        if re.search(rf"\b{code}\b", t, flags=re.IGNORECASE):
            return code
    for sym in sorted(CURRENCY_SYMBOLS, key=len, reverse=True):
        if sym in t:
            return CURRENCY_SYMBOLS[sym]
    return default


def parse_amount_cents(text: str | None) -> int:
    """Parse one money string into integer cents.

    Raises AmountParseError when the string has no number, more than one number, a negative
    value, zero, or an ambiguous separator layout such as ``1,234,5``.
    """
    if text is None or not text.strip():
        raise AmountParseError("empty amount")
    cleaned = text.replace("\u00a0", " ").strip()
    if "-" in cleaned.split()[0] or cleaned.startswith("(") and cleaned.endswith(")"):
        raise AmountParseError(f"negative amount not allowed: {text!r}")
    matches = _NUM_RE.findall(cleaned)
    if not matches:
        raise AmountParseError(f"no number in {text!r}")
    if len(matches) > 1:
        raise AmountParseError(f"more than one number in {text!r}")
    raw = matches[0].replace(" ", "").replace("\u00a0", "")
    dots, commas = raw.count("."), raw.count(",")
    if dots and commas:
        # The last separator is the decimal mark; the other must be a thousands grouping.
        last_dot, last_comma = raw.rfind("."), raw.rfind(",")
        if last_dot > last_comma:
            int_part, frac = raw[:last_dot].replace(",", ""), raw[last_dot + 1 :]
            if "." in int_part:
                raise AmountParseError(f"ambiguous separators in {text!r}")
        else:
            int_part, frac = raw[:last_comma].replace(".", ""), raw[last_comma + 1 :]
            if "," in int_part:
                raise AmountParseError(f"ambiguous separators in {text!r}")
    elif commas:
        parts = raw.split(",")
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            int_part, frac = parts[0], parts[1]
        elif all(len(p) == 3 for p in parts[1:]):
            int_part, frac = "".join(parts), "0"
        else:
            raise AmountParseError(f"ambiguous separators in {text!r}")
    elif dots:
        parts = raw.split(".")
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            int_part, frac = parts[0], parts[1]
        elif all(len(p) == 3 for p in parts[1:]):
            int_part, frac = "".join(parts), "0"
        else:
            raise AmountParseError(f"ambiguous separators in {text!r}")
    else:
        int_part, frac = raw, "0"
    if not int_part.isdigit() or not frac.isdigit():
        raise AmountParseError(f"not a number: {text!r}")
    frac = (frac + "00")[:2]
    cents = int(int_part) * 100 + int(frac)
    if cents <= 0:
        raise AmountParseError(f"amount must be positive: {text!r}")
    return cents


def format_cents(cents: int, currency: str = "USD") -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    whole, frac = divmod(cents, 100)
    body = f"{whole:,}.{frac:02d}" if frac else f"{whole:,}"
    prefix = "$" if currency == "USD" else f"{currency} "
    return f"{sign}{prefix}{body}"


_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}


def parse_date(text: str | None, *, day_first: bool = False) -> date | None:
    """Parse common invoice date spellings. Returns None when nothing parses cleanly."""
    if not text:
        return None
    t = text.strip().rstrip(".")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if "." in t or day_first:
            d, mo = a, b
        else:
            mo, d = a, b
        if a > 12 and b <= 12:
            d, mo = a, b
        elif b > 12 and a <= 12:
            mo, d = a, b
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})", t)
    if m and m.group(2).lower() in _MONTHS:
        try:
            return date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
        except ValueError:
            return None
    m = re.fullmatch(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", t)
    if m and m.group(1).lower() in _MONTHS:
        try:
            return date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
        except ValueError:
            return None
    return None


def digits_only(text: str | None) -> str | None:
    if not text:
        return None
    d = re.sub(r"\D", "", text)
    return d or None


def normalize_account(text: str | None) -> str | None:
    """Bank accounts and IBANs: keep letters and digits, uppercase (IBAN check letters matter)."""
    if not text:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9]", "", text).upper()
    return cleaned or None


def email_domain(addr: str | None) -> str | None:
    if not addr or "@" not in addr:
        return None
    dom = addr.rsplit("@", 1)[1].strip().strip(">").lower()
    return dom or None
