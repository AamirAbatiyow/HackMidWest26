"""Deterministic trust score, status and risk from the structured findings.

Every point is attached to a named evidence factor so the owner can see exactly why. The
model never changes these numbers; it only writes the plain-English summary afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..intake.amounts import format_cents
from ..models import (
    BankChangeFindings,
    DupSplitFindings,
    EvidenceFactor,
    ParsedInvoice,
    RingFindings,
    RiskType,
    SenderFindings,
    Vendor,
    VendorResolution,
    VouchStatus,
)

MIN_TRUST, MAX_TRUST = 2, 98


@dataclass
class ScoreInputs:
    parsed: ParsedInvoice
    vendor: Vendor | None
    resolution: VendorResolution
    sender: SenderFindings | None
    bank_change: BankChangeFindings
    dup_split: DupSplitFindings
    ring: RingFindings
    today: date
    approval_limit_cents: int
    new_vendor_limit_cents: int
    related_invoice_numbers: dict[str, str] = field(default_factory=dict)  # payment id → invoice number


@dataclass
class ScoreResult:
    trust: int
    status: VouchStatus
    risk: RiskType
    fast_pay_eligible: bool
    evidence: list[EvidenceFactor]
    base: float


def _month(d: date) -> str:
    return d.strftime("%b %Y")


def _days(n: int) -> str:
    if n == 0:
        return "today"
    return "1 day ago" if n == 1 else f"{n} days ago"


def score(inp: ScoreInputs) -> ScoreResult:
    ev: list[EvidenceFactor] = []
    n = [0]

    def add(label: str, weight: float, direction: str, points: float) -> None:
        n[0] += 1
        ev.append(
            EvidenceFactor(id=f"e{n[0]}", label=label, weight=weight, direction=direction, points=points)
        )  # type: ignore[arg-type]

    v = inp.vendor
    p = inp.parsed
    amount = p.amount_cents or 0
    known = inp.resolution.status == "known" and v is not None
    new_vendor = v is None or (v.payments_completed == 0)

    if known and v is not None and not new_vendor:
        base = 60 + min(20.0, v.payments_completed * 0.3)
    elif inp.resolution.status == "uncertain":
        base = 50.0
    else:
        base = 40.0

    # --- bank details (account takeover) ---
    bc = inp.bank_change
    if bc.changed:
        if bc.days_since_change is not None:
            add(f"Bank account changed {_days(bc.days_since_change)}", 0.95, "concern", -22)
        if "invoice_lists_account_not_on_file" in bc.flags:
            add("Invoice lists a bank account that is not on file", 0.95, "concern", -25)
        if "change_came_from_new_or_lookalike_sender" in bc.flags or (
            inp.sender and "new_sender_for_known_vendor" in inp.sender.flags
        ):
            add("Change request came from a new email address", 0.6, "concern", -4)
        if bc.country_changed:
            add("New bank is in a different country than before", 0.45, "concern", -3)
    elif known and v is not None and v.current_bank is not None and not new_vendor:
        add(f"Same bank account since {_month(v.current_bank.since)}", 0.9, "reassuring", 8)

    # --- history ---
    if known and v is not None and not new_vendor:
        if v.disputes == 0:
            add(f"{v.payments_completed} payments completed, none disputed", 0.8, "reassuring", 5)
        else:
            add(f"{v.payments_completed} payments completed, {v.disputes} disputed", 0.5, "concern", -4)
        if v.typical_amount_cents and amount and not inp.dup_split.split_with:
            ratio = amount / v.typical_amount_cents
            if 0.6 <= ratio <= 1.6:
                add("Amount is in the usual range for this vendor", 0.5, "reassuring", 4)
            elif ratio > 2.5:
                add(
                    f"Amount is well above the usual {format_cents(v.typical_amount_cents)} for this vendor",
                    0.6,
                    "concern",
                    -6,
                )
    if p.fields.po_number:
        add(f"References purchase order {p.fields.po_number}", 0.5, "reassuring", 2)

    # --- sender ---
    s = inp.sender
    if s is not None and s.from_domain:
        if s.lookalike and s.lookalike.is_lookalike:
            add(
                f"Sender domain {s.from_domain} looks like {s.lookalike.closest_known_domain} but is not it",
                0.7,
                "concern",
                -8,
            )
        if s.reply_to_mismatch:
            add(f"Replies go to a different domain ({s.reply_to_domain})", 0.5, "concern", -5)
        if "dmarc_fail" in s.flags:
            add("Email failed DMARC authentication", 0.6, "concern", -6)
        elif any(fl.startswith(("spf_", "dkim_")) and fl not in ("dkim_missing",) for fl in s.flags):
            add("Email failed sender authentication (SPF/DKIM)", 0.5, "concern", -4)
        if known and s.auth_pass and s.lookalike and s.lookalike.is_known and not s.reply_to_mismatch:
            add("Invoice arrived from the usual address, authentication passed", 0.5, "reassuring", 3)
        if "freemail_sender" in s.flags and known and not new_vendor:
            add("Sent from a free webmail address, not the vendor's domain", 0.5, "concern", -5)

    # --- duplicates / splits ---
    ds = inp.dup_split
    if ds.duplicate_of:
        other = inp.related_invoice_numbers.get(ds.duplicate_of, ds.duplicate_of)
        add(f"Same invoice number as {other} already in this batch", 0.9, "concern", 0)
        if ds.minutes_apart is not None:
            add(f"Same amount, arrived {ds.minutes_apart} minutes later", 0.7, "concern", 0)
        if known and not new_vendor:
            add("Trusted vendor, probably an honest resend", 0.75, "reassuring", 0)
    if ds.split_with:
        others = ", ".join(inp.related_invoice_numbers.get(i, i) for i in ds.split_with)
        add(f"Pairs with {others}, sent {ds.minutes_apart} minutes apart", 0.85, "concern", -8)
        if ds.under_limit_pattern:
            add(
                f"Both sit just under your {format_cents(inp.approval_limit_cents)} approval limit",
                0.7,
                "concern",
                -4,
            )
        if ds.combined_cents:
            add(f"Together they total {format_cents(ds.combined_cents)}, above the limit", 0.6, "concern", 0)
        if v is not None and v.typical_amount_cents and v.typical_amount_cents > amount * 1.5:
            add(
                f"Usual single order from this vendor is about {format_cents(v.typical_amount_cents)}",
                0.5,
                "concern",
                0,
            )

    # --- vendor network / new vendor ---
    r = inp.ring
    if r.shared_bank_with:
        add(f"Same bank account as {len(r.shared_bank_with)} other vendor(s)", 1.0, "concern", -15)
    if r.shared_phone_with:
        add(f"Same phone number as {r.shared_phone_with[0]}", 0.75, "concern", -5)
    if r.shared_address_with:
        add(f"Same mailing address as {r.shared_address_with[0]}", 0.4, "concern", -3)
    if r.virtual_office:
        add("Mailing address is a virtual office", 0.4, "concern", -2)

    if inp.resolution.status == "uncertain":
        top = inp.resolution.candidates[0].name if inp.resolution.candidates else "a vendor on file"
        add(f"Vendor name resembles {top} but is not an exact match", 0.6, "concern", -10)
    if new_vendor:
        if v is not None:
            age = (inp.today - v.since).days
            if v.verified_by_callback:
                add("Bank account verified by call-back on day one", 0.8, "reassuring", 20)
            if v.registration_verified:
                add("Business registration matches the bank account name", 0.85, "reassuring", 12)
            if age <= 14 and not v.verified_by_callback:
                add(f"Registered {age} days ago, first invoice", 0.6, "concern", -3)
        else:
            add("Vendor is not in your directory yet", 0.7, "concern", -5)
        if amount and amount <= inp.new_vendor_limit_cents:
            add("Small first payment, within your new-vendor limit", 0.6, "reassuring", 4)
        add("No history yet", 0.25, "concern", -4)
        if not r.flags and p.amount_cents and p.fields.invoice_number and p.due_date:
            add("Invoice format is clean and complete", 0.2, "reassuring", 3)
        elif r.flags and p.amount_cents and p.fields.invoice_number:
            add("Invoice format is clean and complete", 0.2, "reassuring", 3)

    if p.amount_cents is None:
        add("Could not read the total reliably; needs a human look", 0.8, "concern", -15)
    if p.provenance_violations:
        add("Some extracted fields were not quotes from the invoice and were discarded", 0.3, "concern", -2)

    trust = int(round(max(MIN_TRUST, min(MAX_TRUST, base + sum(e.points for e in ev)))))

    # --- status / risk (holds only, never a denial) ---
    unverified_change = bc.changed and bc.requester_verified is not True
    verify = (
        unverified_change
        or bool(r.shared_bank_with)
        or trust < 35
        or p.amount_cents is None
        or (s is not None and s.lookalike is not None and s.lookalike.is_lookalike and s.reply_to_mismatch)
    )
    quick = (
        bool(ds.duplicate_of)
        or bool(ds.split_with)
        or inp.resolution.status == "uncertain"
        or trust < 65
        or (s is not None and s.risk >= 0.3)
        or bool(r.flags)
        or (new_vendor and not (v is not None and (v.verified_by_callback or v.registration_verified)))
    )
    status: VouchStatus = "verify" if verify else "quick_check" if quick else "vouched"

    if bc.changed:
        risk: RiskType = "changed_bank"
    elif (
        r.flags
        or inp.resolution.status != "known"
        and not (v is not None and (v.verified_by_callback or v.registration_verified))
    ):
        risk = "unrecognized_vendor" if (r.flags or status != "vouched") else "none"
    elif ds.duplicate_of or ds.split_with:
        risk = "duplicate_or_split"
    else:
        risk = "none"
    if risk == "none" and (ds.duplicate_of or ds.split_with):
        risk = "duplicate_or_split"

    fast = (
        status == "vouched"
        and amount > 0
        and amount <= inp.approval_limit_cents * 2
        and (
            (known and v is not None and v.payments_completed >= 20)
            or (v is not None and v.verified_by_callback and amount <= inp.new_vendor_limit_cents)
        )
        and (s is None or s.risk < 0.2)
    )
    return ScoreResult(trust=trust, status=status, risk=risk, fast_pay_eligible=fast, evidence=ev, base=base)
