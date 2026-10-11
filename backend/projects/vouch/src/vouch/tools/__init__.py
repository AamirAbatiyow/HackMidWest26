"""Read-only evidence tools for the investigator agents. No tool here can move money or edit records."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vouch.identity import address_is_virtual, phone_is_voip, tax_id_valid
from vouch.kernel import format_cents

if TYPE_CHECKING:
    from vouch.engine import VouchEngine


def evidence_functions(service: VouchEngine) -> dict[str, Any]:
    def vendor_profile(vendor_id: str) -> dict[str, Any]:
        """Vendor master-file record with identity checks (tax id checksum, VOIP phone, virtual address).

        Args:
            vendor_id: Vendor id from the facts.
        """
        v = service.vendors.get(vendor_id)
        if v is None:
            return {"error": "unknown vendor"}
        return {
            "name": v.name,
            "country": v.country,
            "created_days_ago": v.created_days_ago,
            "phone_on_file": v.phone,
            "email_on_file": v.email,
            "bank_account_masked": "****" + v.bank_account[-4:],
            "tax_id_valid": tax_id_valid(v.tax_id),
            "phone_voip": phone_is_voip(v.phone),
            "address_virtual": address_is_virtual(v.address),
            "verified_out_of_band": v.oob_verified,
        }

    def payment_history(vendor_id: str) -> dict[str, Any]:
        """Past payments to this vendor (most recent first).

        Args:
            vendor_id: Vendor id from the facts.
        """
        v = service.vendors.get(vendor_id)
        if v is None:
            return {"error": "unknown vendor"}
        recent = sorted(v.history, key=lambda p: p.days_ago)[:8]
        return {
            "count": len(v.history),
            "recent": [
                {
                    "amount": format_cents(p.amount_cents),
                    "days_ago": p.days_ago,
                    "invoice_number": p.invoice_number,
                }
                for p in recent
            ],
        }

    def bank_change_log(vendor_id: str) -> dict[str, Any]:
        """Bank-detail change history on the master file and whether it was confirmed out-of-band.

        Args:
            vendor_id: Vendor id from the facts.
        """
        v = service.vendors.get(vendor_id)
        if v is None:
            return {"error": "unknown vendor"}
        return {
            "bank_changed_days_ago": v.bank_changed_days_ago,
            "confirmed_out_of_band": v.bank_change_confirmed_oob,
            "contact_changed_days_ago": v.contact_changed_days_ago,
        }

    def linked_vendors(vendor_id: str) -> dict[str, Any]:
        """Other vendors sharing a bank account, tax id, phone, address or email domain with this vendor.

        Args:
            vendor_id: Vendor id from the facts.
        """
        shared = service.graph.shared(vendor_id)
        return {
            kind: [service.vendors[o].name for o in ids if o in service.vendors]
            for kind, ids in shared.items()
        }

    return {
        "vendor_profile": vendor_profile,
        "payment_history": payment_history,
        "bank_change_log": bank_change_log,
        "linked_vendors": linked_vendors,
    }


def get_tools(service: VouchEngine) -> list[Any]:
    from strands import tool

    return [tool(fn) for fn in evidence_functions(service).values()]
