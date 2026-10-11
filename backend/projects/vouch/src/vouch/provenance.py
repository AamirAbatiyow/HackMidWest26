"""Provenance check: every number in LLM-written text must be a kernel/model fact.

Numbers are extracted from both the text and the fact values with the same tokenizer and compared in
normalized form ($1,234.50 == 1234.5, Oct 12, 2026 == 2026-10-12). Anything else, including invoice
or account numbers the LLM made up, fails the check and the caller falls back to a deterministic
template. Small counting words/digits (0-10) without a currency or percent sign are allowed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from vouch.kernel import parse_date

_TEXT_DATE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b"
)
_SLASH_DATE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")
_TOKEN = re.compile(
    r"(?P<date>\b\d{4}-\d{2}-\d{2}\b)"
    r"|(?P<money>(?:[$€£]|\b(?:USD|EUR|XRP)\s?)\s?\d[\d,]*(?:\.\d+)?)"
    r"|(?P<pct>\d+(?:\.\d+)?\s?%)"
    r"|(?P<num>\d[\d,]*(?:\.\d+)?)"
)
SMALL_COUNTS = {str(i) for i in range(11)}


def _canonical_number(raw: str) -> str | None:
    digits = re.sub(r"[^\d.]", "", raw)
    if not digits:
        return None
    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None
    return format(value.normalize(), "f")


def extract_numbers(text: str) -> list[tuple[str, str]]:
    """Return (kind, canonical) pairs found in `text`."""
    found: list[tuple[str, str]] = []

    def _date_sub(m: re.Match[str]) -> str:
        d = parse_date(m.group(0))
        if d:
            found.append(("date", d.isoformat()))
        return " "

    text = _TEXT_DATE.sub(_date_sub, text or "")
    text = _SLASH_DATE.sub(_date_sub, text)
    for m in _TOKEN.finditer(text):
        kind = m.lastgroup or "num"
        raw = m.group(0)
        if kind == "date":
            found.append(("date", raw))
        elif kind == "pct":
            canon = _canonical_number(raw)
            if canon is not None:
                found.append(("pct", canon))
        else:
            canon = _canonical_number(raw)
            if canon is not None:
                found.append(("money" if kind == "money" else "num", canon))
    return found


def allowed_set(fact_values: Iterable[str]) -> set[tuple[str, str]]:
    allowed: set[tuple[str, str]] = set()
    for value in fact_values:
        for kind, canon in extract_numbers(value):
            allowed.add((kind, canon))
            if kind in ("money", "num"):
                # A fact amount may be cited with or without its currency sign.
                allowed.add(("money", canon))
                allowed.add(("num", canon))
    return allowed


@dataclass
class ProvenanceReport:
    ok: bool
    unknown: list[str] = field(default_factory=list)
    checked: int = 0


def check_provenance(text: str, fact_values: Iterable[str]) -> ProvenanceReport:
    allowed = allowed_set(fact_values)
    unknown = []
    tokens = extract_numbers(text)
    for kind, canon in tokens:
        if kind == "num" and canon in SMALL_COUNTS:
            continue
        if (kind, canon) not in allowed:
            unknown.append(f"{kind}:{canon}")
    return ProvenanceReport(ok=not unknown, unknown=unknown, checked=len(tokens))
