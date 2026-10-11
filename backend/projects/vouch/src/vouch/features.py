"""Feature extraction shared by training and serving (one code path, so no train/serve skew)."""

from __future__ import annotations

import math
from typing import Any

from vouch.domain import Invoice, Vendor
from vouch.graph_features import VendorGraph, identity_suspicion
from vouch.identity import (
    PUBLIC_EMAIL_DOMAINS,
    address_is_virtual,
    email_domain,
    phone_is_voip,
    tax_id_valid,
)
from vouch.kernel import InvoiceChecks

NUMERIC_FEATURES = [
    "amount_log",
    "amount_vs_history",
    "amount_creep",
    "vendor_age_log",
    "history_count_log",
    "new_vendor",
    "bank_mismatch",
    "bank_change_unconfirmed",
    "bank_change_confirmed",
    "contact_change_recent",
    "remit_email_mismatch",
    "foreign_bank",
    "urgency_terms",
    "injection_text",
    "has_po",
    "delivery_confirmed",
    "duplicate_suspect",
    "split_suspect",
    "near_approval_limit",
    "round_amount",
    "line_items_mismatch",
    "tax_id_invalid",
    "phone_voip",
    "address_virtual",
    "free_email",
    "oob_verified",
    "identity_suspicion",
    "shared_bank",
    "shared_tax_id",
    "shared_phone",
    "shared_address",
    "shared_email_domain",
    "component_size_log",
    "component_new_share",
    "neighbour_suspicion",
]
CATEGORICAL_FEATURES = ["country", "category", "submitted_by", "bank_country"]

# Human-readable names used in LIME output shown to the owner.
FEATURE_LABELS = {
    "amount_log": "invoice amount",
    "amount_vs_history": "amount vs. vendor's usual",
    "amount_creep": "amounts creeping up over time",
    "vendor_age_log": "vendor age",
    "history_count_log": "payment history length",
    "new_vendor": "vendor is new (<60 days)",
    "bank_mismatch": "invoice bank differs from master file",
    "bank_change_unconfirmed": "unconfirmed bank change",
    "bank_change_confirmed": "bank change confirmed out-of-band",
    "contact_change_recent": "recent contact change",
    "remit_email_mismatch": "remit email domain mismatch",
    "foreign_bank": "bank country differs from vendor country",
    "urgency_terms": "urgency language",
    "injection_text": "instructions aimed at the system",
    "has_po": "has purchase order",
    "delivery_confirmed": "delivery confirmed",
    "duplicate_suspect": "possible duplicate",
    "split_suspect": "possible split invoice",
    "near_approval_limit": "just under approval limit",
    "round_amount": "round-thousand amount",
    "line_items_mismatch": "line items don't add up",
    "tax_id_invalid": "tax id fails checksum",
    "phone_voip": "VOIP / toll-free phone",
    "address_virtual": "virtual / PO box address",
    "free_email": "free email provider",
    "oob_verified": "identity verified out-of-band",
    "identity_suspicion": "identity red flags",
    "shared_bank": "bank account shared with other vendors",
    "shared_tax_id": "tax id shared with other vendors",
    "shared_phone": "phone shared with other vendors",
    "shared_address": "address shared with other vendors",
    "shared_email_domain": "email domain shared with other vendors",
    "component_size_log": "size of linked-vendor cluster",
    "component_new_share": "share of new vendors in cluster",
    "neighbour_suspicion": "red flags among linked vendors",
}


def _log(x: float) -> float:
    return math.log1p(max(x, 0.0))


def invoice_features(
    inv: Invoice, vendor: Vendor | None, checks: InvoiceChecks, graph: VendorGraph | None
) -> tuple[dict[str, float], dict[str, str]]:
    g = graph.features(vendor.id) if (graph and vendor) else {}
    created = vendor.created_days_ago if vendor else 0
    domain = email_domain(vendor.email) if vendor else ""
    numeric = {
        "amount_log": _log(inv.amount_cents / 100),
        "amount_vs_history": min(checks.amount_ratio_milli / 1000, 10.0) if checks.history_count else 1.0,
        "amount_creep": max(min(checks.creep_milli / 1000, 3.0), -1.0),
        "vendor_age_log": _log(created),
        "history_count_log": _log(checks.history_count),
        "new_vendor": float(created <= 60),
        "bank_mismatch": float(checks.bank_mismatch),
        "bank_change_unconfirmed": float(checks.bank_change_recent and not checks.bank_change_confirmed),
        "bank_change_confirmed": float(checks.bank_change_recent and checks.bank_change_confirmed),
        "contact_change_recent": float(checks.contact_change_recent),
        "remit_email_mismatch": float(checks.remit_email_mismatch),
        "foreign_bank": float(bool(vendor) and vendor.bank_country != vendor.country),
        "urgency_terms": float(min(checks.urgency_terms, 5)),
        "injection_text": float(bool(checks.injection)),
        "has_po": float(not checks.no_po),
        "delivery_confirmed": float(not checks.no_delivery),
        "duplicate_suspect": float(checks.duplicate_of is not None),
        "split_suspect": float(bool(checks.split_group)),
        "near_approval_limit": float(checks.near_approval_limit),
        "round_amount": float(inv.amount_cents % 100_000 == 0),
        "line_items_mismatch": float(not checks.line_items_match),
        "tax_id_invalid": float(bool(vendor) and not tax_id_valid(vendor.tax_id)),
        "phone_voip": float(bool(vendor) and phone_is_voip(vendor.phone)),
        "address_virtual": float(bool(vendor) and address_is_virtual(vendor.address)),
        "free_email": float(domain in PUBLIC_EMAIL_DOMAINS),
        "oob_verified": float(bool(vendor) and vendor.oob_verified),
        "identity_suspicion": identity_suspicion(vendor) if vendor else 1.0,
        "shared_bank": min(g.get("shared_bank", 0.0), 5.0),
        "shared_tax_id": min(g.get("shared_tax_id", 0.0), 5.0),
        "shared_phone": min(g.get("shared_phone", 0.0), 5.0),
        "shared_address": min(g.get("shared_address", 0.0), 5.0),
        "shared_email_domain": min(g.get("shared_email_domain", 0.0), 5.0),
        "component_size_log": _log(g.get("component_size", 1.0)),
        "component_new_share": g.get("component_new_share", 0.0),
        "neighbour_suspicion": g.get("neighbour_suspicion", 0.0),
    }
    categorical = {
        "country": vendor.country if vendor else "UNK",
        "category": vendor.category if vendor else "UNK",
        "submitted_by": inv.submitted_by,
        "bank_country": vendor.bank_country if vendor else "UNK",
    }
    return numeric, categorical


def feature_rows(items: list[dict[str, Any]]) -> list[list[float]]:
    return [[float(it[name]) for name in NUMERIC_FEATURES] for it in items]
