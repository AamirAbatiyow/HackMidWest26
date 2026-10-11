"""Regex extraction of the identity an invoice *claims* (tax id, phone, address, email, bank account).

These strings are only ever used to look the vendor up on the master file; the kernel owns every
monetary field (`vouch.kernel.parse_invoice_text`). Nothing here is produced by an LLM.
"""

from __future__ import annotations

import re

from ..contracts import VendorClaim, digits_only
from ..kernel import normalize_account, parse_invoice_text

_TAX_ID = re.compile(
    r"(?:tax\s*id|ein|vat(?:\s*(?:no|number|id))?|rfc|nip|cnpj|steuernummer|ust-?id)\s*[:#.]?\s*"
    r"([A-Z]{0,3}\s?[\dA-Z][\dA-Z .\-/]{6,24}[\dA-Z])",
    re.I,
)
_PHONE = re.compile(r"(?:tel|phone|ph|mobile|call)\.?\s*[:#]?\s*(\+?[\d][\d\s().\-]{7,20}\d)", re.I)
_ADDRESS = re.compile(
    r"(\d{1,6}\s+[A-Za-z0-9.'\- ]{3,50}\b(?:st|street|ave|avenue|blvd|boulevard|rd|road|dr|drive|"
    r"ln|lane|way|pike|pkwy|parkway|hwy|highway|suite|ste|pmb|box|green|plaza|strasse|straße)\b[^\n]{0,40})",
    re.I,
)
_PO_BOX = re.compile(r"(P\.?O\.?\s*Box\s+\d+[^\n]{0,40})", re.I)


def extract_claim(text: str, *, sender_email: str | None = None) -> VendorClaim:
    parsed = parse_invoice_text(text or "")
    claim = VendorClaim(
        name=parsed.fields.get("vendor_name"),
        email=parsed.fields.get("remit_email") or sender_email,
        bank_account=normalize_account(parsed.fields.get("bank_account")),
    )
    if m := _TAX_ID.search(text or ""):
        raw = m.group(1).strip()
        claim.tax_id = raw if digits_only(raw) and len(digits_only(raw) or "") >= 7 else None
    if m := _PHONE.search(text or ""):
        claim.phone = m.group(1).strip()
    if m := _PO_BOX.search(text or "") or _ADDRESS.search(text or ""):
        claim.address = m.group(1).strip(" ,.")
    return claim
