"""Lookup index over the vendor master file (the engine's `Vendor` records) by the identifiers an
invoice can carry: tax id, email domain, bank account, phone, street address."""

from __future__ import annotations

import re

from ..contracts import digits_only, email_domain
from ..domain import Vendor
from ..identity import PUBLIC_EMAIL_DOMAINS
from ..kernel import normalize_account


def normalize_address(addr: str | None) -> str:
    if not addr:
        return ""
    s = addr.lower()
    s = re.sub(r"\b(suite|ste|unit|#|apt|floor|fl)\b\.?\s*[\w-]+", " ", s)
    s = s.replace("street", "st").replace("avenue", "ave").replace("north", "n").replace("south", "s")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(s.split())


def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    s = name.lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(
        r"\b(inc|llc|ltd|co|corp|corporation|company|sp z o o|s a|sa de cv|gmbh|me|ltda|pvt|the)\b", " ", s
    )
    return " ".join(s.split())


class VendorDirectory:
    def __init__(self, vendors: list[Vendor] | None = None) -> None:
        self._vendors: dict[str, Vendor] = {}
        for v in vendors or []:
            self.add(v)

    def add(self, vendor: Vendor) -> None:
        self._vendors[vendor.id] = vendor

    def get(self, vendor_id: str | None) -> Vendor | None:
        return self._vendors.get(vendor_id or "")

    def all(self) -> list[Vendor]:
        return list(self._vendors.values())

    def __len__(self) -> int:
        return len(self._vendors)

    @staticmethod
    def domains_of(vendor: Vendor) -> list[str]:
        d = email_domain(vendor.email)
        return [d] if d else []

    def by_tax_id(self, tax_id: str | None) -> Vendor | None:
        digits = digits_only(tax_id)
        if not digits:
            return None
        return next((v for v in self._vendors.values() if digits_only(v.tax_id) == digits), None)

    def by_domain(self, domain: str | None) -> Vendor | None:
        d = (domain or "").lower().strip()
        if not d or d in PUBLIC_EMAIL_DOMAINS:
            return None  # a free-mail domain identifies nobody
        return next((v for v in self._vendors.values() if d in self.domains_of(v)), None)

    def by_bank_account(self, account: str | None) -> list[Vendor]:
        acct = normalize_account(account)
        if not acct:
            return []
        return [
            v
            for v in self._vendors.values()
            if normalize_account(v.bank_account) == acct or normalize_account(v.previous_bank_account) == acct
        ]

    def by_phone(self, phone: str | None) -> list[Vendor]:
        digits = digits_only(phone)
        if not digits:
            return []
        tail = digits[-10:]
        return [v for v in self._vendors.values() if (digits_only(v.phone) or "")[-10:] == tail]

    def by_address(self, addr: str | None) -> list[Vendor]:
        key = normalize_address(addr)
        if not key:
            return []
        return [v for v in self._vendors.values() if v.address and normalize_address(v.address) == key]

    def known_domains(self) -> list[str]:
        return sorted({d for v in self._vendors.values() for d in self.domains_of(v)})
