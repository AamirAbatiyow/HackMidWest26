"""Lookalike-domain detection against the known vendor domains.

Combines homoglyph normalization (``rn``→``m``, ``0``→``o``, Cyrillic/Greek confusables),
decorative-suffix stripping (``-eu``, ``-billing``…) and Levenshtein distance.
"""

from __future__ import annotations

import unicodedata

from rapidfuzz.distance import Levenshtein

from ..models import LookalikeFinding

_CONFUSABLES = {
    "0": "o",
    "1": "l",
    "3": "e",
    "5": "s",
    "7": "t",
    "8": "b",
    "|": "l",
    "а": "a",  # Cyrillic
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "у": "y",
    "х": "x",
    "і": "i",
    "ј": "j",
    "ѕ": "s",
    "ԁ": "d",
    "ɡ": "g",
    "ο": "o",  # Greek
    "α": "a",
    "ν": "v",
    "τ": "t",
    "ⅼ": "l",
}
_MULTI = [("rn", "m"), ("vv", "w"), ("cl", "d"), ("nn", "m")]
_DECOR_SUFFIXES = (
    "-eu",
    "-us",
    "-uk",
    "-inc",
    "-llc",
    "-ltd",
    "-pay",
    "-payments",
    "-billing",
    "-invoice",
    "-invoices",
    "-finance",
    "-accounts",
    "-ar",
    "-group",
    "-global",
    "-online",
    "-secure",
    "-mail",
    "-corp",
)
FREEMAIL = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "yahoo.com",
    "icloud.com",
    "proton.me",
    "protonmail.com",
    "aol.com",
    "mail.com",
    "gmx.com",
}


def registrable_label(domain: str) -> str:
    """'ar.warsawsteel.pl' → 'warsawsteel' (best effort, ccTLD second levels handled)."""
    parts = domain.lower().strip(".").split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net", "gov", "ac"} and len(parts[-1]) == 2:
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else parts[0]


def homoglyph_normalize(label: str) -> str:
    s = unicodedata.normalize("NFKC", label.lower())
    s = "".join(_CONFUSABLES.get(ch, ch) for ch in s)
    for a, b in _MULTI:
        s = s.replace(a, b)
    return s


def strip_decoration(label: str) -> str:
    for suf in _DECOR_SUFFIXES:
        if label.endswith(suf) and len(label) > len(suf) + 3:
            return label[: -len(suf)]
    for pre in ("secure-", "billing-", "pay-", "invoice-", "ar-", "mail-"):
        if label.startswith(pre) and len(label) > len(pre) + 3:
            return label[len(pre) :]
    return label


def check_lookalike(domain: str, known_domains: list[str]) -> LookalikeFinding:
    domain = (domain or "").lower().strip()
    finding = LookalikeFinding(domain=domain)
    if not domain:
        finding.detail = "no sender domain"
        return finding
    known = sorted({d.lower() for d in known_domains if d})
    if domain in known:
        finding.is_known = True
        finding.closest_known_domain = domain
        finding.distance = 0
        finding.detail = "sender domain is on file for a vendor"
        return finding
    label = registrable_label(domain)
    norm = homoglyph_normalize(strip_decoration(label))
    best: tuple[int, str] | None = None
    for kd in known:
        klabel = registrable_label(kd)
        knorm = homoglyph_normalize(klabel)
        if norm == knorm and label != klabel:
            finding.homoglyph_normalized_match = True
            finding.is_lookalike = True
            finding.closest_known_domain = kd
            finding.distance = Levenshtein.distance(label, klabel)
            finding.detail = f"'{domain}' normalizes to '{kd}' (homoglyphs or decorative suffix)"
            return finding
        if norm == knorm and label == klabel:
            # Same registrable label, different TLD (warsawsteel.pl vs warsawsteel.com).
            finding.is_lookalike = True
            finding.closest_known_domain = kd
            finding.distance = Levenshtein.distance(domain, kd)
            finding.detail = f"'{domain}' reuses the name of '{kd}' under a different TLD"
            return finding
        if len(knorm) >= 5 and knorm in norm and norm != knorm:
            finding.is_lookalike = True
            finding.closest_known_domain = kd
            finding.distance = Levenshtein.distance(label, klabel)
            finding.detail = f"'{domain}' contains the vendor name from '{kd}'"
            return finding
        dist = Levenshtein.distance(norm, knorm)
        if best is None or dist < best[0]:
            best = (dist, kd)
    if best is not None:
        finding.closest_known_domain = best[1]
        finding.distance = best[0]
        klabel = registrable_label(best[1])
        threshold = 1 if len(klabel) < 6 else 2
        if best[0] <= threshold and best[0] > 0:
            finding.is_lookalike = True
            finding.detail = f"'{domain}' is {best[0]} edit(s) away from '{best[1]}'"
        else:
            finding.detail = f"closest vendor domain is '{best[1]}' ({best[0]} edits)"
    return finding
