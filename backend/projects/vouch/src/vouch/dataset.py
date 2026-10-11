"""Turn a synthetic World into model rows using the same kernel + graph + feature code the pipeline uses."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from vouch.domain import Invoice, Labels, Vendor
from vouch.features import invoice_features
from vouch.graph_features import VendorGraph
from vouch.kernel import InvoiceChecks, Limits, check_invoice
from vouch.synth import World


@dataclass
class Row:
    invoice: Invoice
    vendor: Vendor | None
    checks: InvoiceChecks
    numeric: dict[str, float]
    categorical: dict[str, str]
    label: Labels | None


def build_rows(world: World, limits: Limits | None = None, graph: VendorGraph | None = None) -> list[Row]:
    limits = limits or Limits()
    graph = graph or VendorGraph.build(world.vendors)
    vendors = world.vendor_map()
    by_vendor: dict[str | None, list[Invoice]] = defaultdict(list)
    for inv in world.invoices:
        by_vendor[inv.vendor_id].append(inv)
    rows = []
    for inv in world.invoices:
        vendor = vendors.get(inv.vendor_id or "")
        shared = graph.shared(vendor.id) if vendor else {}
        checks = check_invoice(inv, vendor, by_vendor[inv.vendor_id], limits, world.today, shared)
        numeric, categorical = invoice_features(inv, vendor, checks, graph)
        rows.append(Row(inv, vendor, checks, numeric, categorical, world.labels.get(inv.id)))
    return rows
