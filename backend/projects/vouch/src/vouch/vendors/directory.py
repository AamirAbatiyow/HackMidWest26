"""The owner's vendor directory: lookups by identifiers used during resolution."""

from __future__ import annotations

import re

from ..models import Vendor


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
    s = re.sub(r"\b(inc|llc|ltd|co|corp|corporation|company|sp z o o|s a|sa de cv|gmbh|me|ltda)\b", " ", s)
    return " ".join(s.split())


class VendorDirectory:
    def __init__(self, vendors: list[Vendor] | None = None) -> None:
        self._vendors: dict[str, Vendor] = {}
        for v in vendors or []:
            self.add(v)

    def add(self, vendor: Vendor) -> None:
        self._vendors[vendor.id] = vendor

    def get(self, vendor_id: str) -> Vendor | None:
        return self._vendors.get(vendor_id)

    def all(self) -> list[Vendor]:
        return list(self._vendors.values())

    def __len__(self) -> int:
        return len(self._vendors)

    def by_tax_id(self, digits: str | None) -> Vendor | None:
        if not digits:
            return None
        return next((v for v in self._vendors.values() if v.tax_id_digits == digits), None)

    def by_domain(self, domain: str | None) -> Vendor | None:
        if not domain:
            return None
        return next((v for v in self._vendors.values() if domain.lower() in v.domains), None)

    def by_bank_account(self, account: str | None) -> list[Vendor]:
        if not account:
            return []
        return [v for v in self._vendors.values() if any(b.digits == account for b in v.bank_accounts)]

    def by_phone(self, digits: str | None) -> list[Vendor]:
        if not digits:
            return []
        tail = digits[-10:]
        return [v for v in self._vendors.values() if v.phone_digits and v.phone_digits[-10:] == tail]

    def by_address(self, addr: str | None) -> list[Vendor]:
        key = normalize_address(addr)
        if not key:
            return []
        return [v for v in self._vendors.values() if v.address and normalize_address(v.address) == key]

    def known_domains(self) -> list[str]:
        return [d for v in self._vendors.values() for d in v.domains]
