"""Fake-vendor ring detector: shared bank accounts, phone numbers and addresses across vendors."""

from __future__ import annotations

from ..models import ParsedInvoice, RingEdge, RingFindings, RingGraph, RingNode, Vendor, VendorResolution
from .directory import VendorDirectory, normalize_address

VIRTUAL_OFFICE_HINTS = (
    "1201 n orange st",
    "1209 orange st",
    "1209 n orange st",
    "8 the green",
    "30 n gould st",
    "2093 philadelphia pike",
    "1309 coffeen ave",
    "16192 coastal hwy",
    "251 little falls dr",
    "virtual office",
    "registered agent",
)


def _mask_phone(digits: str) -> str:
    tail = digits[-4:]
    area = digits[-10:-7] if len(digits) >= 10 else ""
    return f"({area}) ···{tail}" if area else f"···{tail}"


def detect_ring(
    parsed: ParsedInvoice,
    resolution: VendorResolution,
    directory: VendorDirectory,
) -> RingFindings:
    findings = RingFindings()
    me = directory.get(resolution.vendor_id) if resolution.vendor_id else None
    my_id = me.id if me else "__candidate__"
    my_name = me.name if me else resolution.vendor_name

    account = parsed.bank_account_digits or (me.current_bank.digits if me and me.current_bank else None)
    phone = parsed.phone_digits or (me.phone_digits if me else None)
    address = parsed.fields.vendor_address or (me.address if me else None)

    shared_bank = [v for v in directory.by_bank_account(account) if v.id != my_id]
    shared_phone = [v for v in directory.by_phone(phone) if v.id != my_id]
    shared_addr = [v for v in directory.by_address(address) if v.id != my_id]
    findings.shared_bank_with = [v.name for v in shared_bank]
    findings.shared_phone_with = [v.name for v in shared_phone]
    findings.shared_address_with = [v.name for v in shared_addr]
    addr_norm = normalize_address(address)
    findings.virtual_office = any(h in addr_norm for h in VIRTUAL_OFFICE_HINTS) if addr_norm else False

    if shared_bank:
        findings.flags.append("shared_bank_account")
    if shared_phone:
        findings.flags.append("shared_phone")
    if shared_addr:
        findings.flags.append("shared_address")
    if findings.virtual_office:
        findings.flags.append("virtual_office_address")

    if shared_bank or shared_phone or shared_addr:
        nodes: dict[str, RingNode] = {my_id: RingNode(id=my_id, label=my_name, kind="vendor", focus=True)}
        edges: list[RingEdge] = []

        def vendor_node(v: Vendor) -> str:
            nodes.setdefault(v.id, RingNode(id=v.id, label=v.name, kind="vendor"))
            return v.id

        if shared_bank and account:
            nodes["bank"] = RingNode(id="bank", label=f"Bank acct ···{account[-4:]}", kind="bank")
            edges.append(RingEdge(**{"from": my_id, "to": "bank"}))
            for v in shared_bank:
                edges.append(RingEdge(**{"from": vendor_node(v), "to": "bank"}))
        if shared_phone and phone:
            nodes["phone"] = RingNode(id="phone", label=_mask_phone(phone), kind="phone")
            edges.append(RingEdge(**{"from": my_id, "to": "phone"}))
            for v in shared_phone:
                edges.append(RingEdge(**{"from": vendor_node(v), "to": "phone"}))
        if shared_addr and address:
            short = address.split(",")[0].strip()
            nodes["addr"] = RingNode(id="addr", label=short, kind="address")
            edges.append(RingEdge(**{"from": my_id, "to": "addr"}))
            for v in shared_addr:
                edges.append(RingEdge(**{"from": vendor_node(v), "to": "addr"}))
        findings.graph = RingGraph(nodes=list(nodes.values()), edges=edges)
    return findings
