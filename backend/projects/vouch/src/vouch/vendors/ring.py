"""Ring graph for the frontend, built from the engine's `VendorGraph` (shared bank / tax id / phone /
address / email domain links). Detection itself lives in `vouch.graph_features`; this only renders it."""

from __future__ import annotations

from ..contracts import RingEdge, RingGraph, RingNode, digits_only
from ..domain import Vendor
from ..graph_features import VendorGraph

_KIND = {"bank": "bank", "phone": "phone", "address": "address", "tax_id": "bank", "email_domain": "address"}


def _label(kind: str, vendor: Vendor) -> str:
    if kind == "bank":
        acct = vendor.bank_account or ""
        return f"Bank acct ···{acct[-4:]}"
    if kind == "tax_id":
        return f"Tax id ···{(digits_only(vendor.tax_id) or '')[-4:]}"
    if kind == "phone":
        d = digits_only(vendor.phone) or ""
        return f"Phone ···{d[-4:]}"
    if kind == "email_domain":
        return f"@{vendor.email.rsplit('@', 1)[-1]}" if vendor.email else "shared domain"
    return (vendor.address or "shared address").split(",")[0].strip()


def ring_graph(graph: VendorGraph, vendors: dict[str, Vendor], vendor_id: str | None) -> RingGraph | None:
    me = vendors.get(vendor_id or "")
    if me is None:
        return None
    shared = graph.shared(me.id)
    if not shared:
        return None
    nodes: dict[str, RingNode] = {me.id: RingNode(id=me.id, label=me.name, kind="vendor", focus=True)}
    edges: list[RingEdge] = []
    for kind, others in shared.items():
        hub = f"{kind}:{me.id}"
        nodes[hub] = RingNode(id=hub, label=_label(kind, me), kind=_KIND.get(kind, "address"))  # type: ignore[arg-type]
        edges.append(RingEdge(**{"from": me.id, "to": hub}))
        for other in others:
            ov = vendors.get(other)
            if ov is None:
                continue
            nodes.setdefault(ov.id, RingNode(id=ov.id, label=ov.name, kind="vendor"))
            edges.append(RingEdge(**{"from": ov.id, "to": hub}))
    return RingGraph(nodes=list(nodes.values()), edges=edges)
