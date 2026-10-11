"""Vendor-attribute graph for ring detection.

Vendors are linked when they share a bank account, tax id, phone, street address, or a non-public email
domain. From that graph we compute per-vendor features (shared-attribute degrees, connected-component
size, share of new vendors in the component) and one round of parameter-free message passing: the mean
"identity suspicion" of a vendor's neighbours. These feed the fake-vendor head of the risk model.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from vouch.domain import Vendor
from vouch.identity import (
    PUBLIC_EMAIL_DOMAINS,
    address_is_virtual,
    email_domain,
    normalize_address,
    normalize_phone,
    phone_is_voip,
    tax_id_valid,
)
from vouch.kernel import normalize_account

ATTRIBUTES = ("bank", "tax_id", "phone", "address", "email_domain")


def _keys(v: Vendor) -> dict[str, str]:
    keys = {
        "bank": normalize_account(v.bank_account) or "",
        "tax_id": "".join(ch for ch in v.tax_id if ch.isdigit()),
        "phone": normalize_phone(v.phone),
        "address": normalize_address(v.address),
    }
    domain = email_domain(v.email)
    if domain and domain not in PUBLIC_EMAIL_DOMAINS:
        keys["email_domain"] = domain
    return {k: val for k, val in keys.items() if val}


def identity_suspicion(v: Vendor) -> float:
    return (
        (not tax_id_valid(v.tax_id))
        + phone_is_voip(v.phone)
        + address_is_virtual(v.address)
        + (v.created_days_ago <= 60)
    ) / 4


@dataclass
class VendorGraph:
    vendors: dict[str, Vendor]
    index: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    component: dict[str, int] = field(default_factory=dict)
    component_members: dict[int, list[str]] = field(default_factory=dict)

    @classmethod
    def build(cls, vendors: list[Vendor]) -> VendorGraph:
        g = cls(vendors={v.id: v for v in vendors})
        index: dict[tuple[str, str], set[str]] = defaultdict(set)
        for v in vendors:
            for kind, key in _keys(v).items():
                index[(kind, key)].add(v.id)
        g.index = dict(index)
        parent = {vid: vid for vid in g.vendors}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for members in g.index.values():
            ids = list(members)
            for other in ids[1:]:
                ra, rb = find(ids[0]), find(other)
                if ra != rb:
                    parent[rb] = ra
        roots: dict[str, int] = {}
        for vid in g.vendors:
            cid = roots.setdefault(find(vid), len(roots))
            g.component[vid] = cid
            g.component_members.setdefault(cid, []).append(vid)
        return g

    def shared(self, vendor_id: str) -> dict[str, list[str]]:
        v = self.vendors.get(vendor_id)
        if v is None:
            return {}
        out: dict[str, list[str]] = {}
        for kind, key in _keys(v).items():
            others = sorted(self.index.get((kind, key), set()) - {vendor_id})
            if others:
                out[kind] = others
        return out

    def neighbours(self, vendor_id: str) -> set[str]:
        return {o for ids in self.shared(vendor_id).values() for o in ids}

    def features(self, vendor_id: str) -> dict[str, float]:
        shared = self.shared(vendor_id)
        members = self.component_members.get(self.component.get(vendor_id, -1), [vendor_id])
        nbrs = self.neighbours(vendor_id)
        new_share = sum(self.vendors[m].created_days_ago <= 60 for m in members) / max(len(members), 1)
        nbr_susp = sum(identity_suspicion(self.vendors[n]) for n in nbrs) / len(nbrs) if nbrs else 0.0
        return {
            "shared_bank": float(len(shared.get("bank", []))),
            "shared_tax_id": float(len(shared.get("tax_id", []))),
            "shared_phone": float(len(shared.get("phone", []))),
            "shared_address": float(len(shared.get("address", []))),
            "shared_email_domain": float(len(shared.get("email_domain", []))),
            "component_size": float(len(members)),
            "component_new_share": new_share if len(members) > 1 else 0.0,
            "neighbour_suspicion": nbr_susp,
        }

    def ring_members(self, vendor_id: str) -> list[str]:
        members = self.component_members.get(self.component.get(vendor_id, -1), [])
        return sorted(m for m in members if m != vendor_id)
