"""Deterministic vendor-identity checks (stand-ins for TIN-matching, phone-carrier and address APIs)."""

from __future__ import annotations

import re

_TAX_WEIGHTS = (3, 7, 1, 3, 7, 1, 3, 7)
# Toll-free / VOIP-heavy prefixes in the synthetic world (real systems ask a carrier-lookup API).
VOIP_PREFIXES = ("+1-888-", "+1-877-", "+1-855-", "+44-70-", "+1-500-")
_VIRTUAL_ADDRESS = re.compile(
    r"\b(p\.?\s?o\.?\s?box|pmb\s*\d+|suite\s+\d+\s*#\s*\d+|mailbox|virtual office)\b", re.I
)
PUBLIC_EMAIL_DOMAINS = {"gmail.com", "outlook.com", "yahoo.com", "proton.me", "hotmail.com"}


def tax_check_digit(first8: str) -> int:
    return sum(int(d) * w for d, w in zip(first8, _TAX_WEIGHTS, strict=True)) % 10


def make_tax_id(first8: str) -> str:
    return f"{first8[:2]}-{first8[2:]}{tax_check_digit(first8)}"


def tax_id_valid(tax_id: str) -> bool:
    digits = re.sub(r"\D", "", tax_id or "")
    return len(digits) == 9 and tax_check_digit(digits[:8]) == int(digits[8])


def phone_is_voip(phone: str) -> bool:
    return (phone or "").startswith(VOIP_PREFIXES)


def address_is_virtual(address: str) -> bool:
    return bool(_VIRTUAL_ADDRESS.search(address or ""))


def normalize_address(address: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (address or "").lower())


def normalize_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def email_domain(email: str) -> str:
    return (email or "").rsplit("@", 1)[-1].lower()
