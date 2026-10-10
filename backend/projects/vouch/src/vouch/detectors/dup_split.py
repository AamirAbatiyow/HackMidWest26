"""Duplicate and split-invoice detection over the payments already in the queue."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from ..models import DupSplitFindings

SPLIT_WINDOW_MINUTES = 60
DUP_WINDOW_HOURS = 72


@dataclass(frozen=True)
class Candidate:
    id: str
    vendor_id: str
    invoice_number: str
    amount_cents: int
    received_at: datetime
    document_sha256: str | None = None


def _norm_inv(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def detect_dup_split(
    candidate: Candidate, existing: list[Candidate], approval_limit_cents: int
) -> DupSplitFindings:
    f = DupSplitFindings()
    same_vendor = [p for p in existing if p.vendor_id == candidate.vendor_id and p.id != candidate.id]
    inv = _norm_inv(candidate.invoice_number)
    earlier = sorted(same_vendor, key=lambda p: p.received_at)
    for p in earlier:
        minutes = abs(int((candidate.received_at - p.received_at).total_seconds() // 60))
        same_doc = bool(candidate.document_sha256) and candidate.document_sha256 == p.document_sha256
        if (inv and _norm_inv(p.invoice_number) == inv) or (
            same_doc and p.amount_cents == candidate.amount_cents
        ):
            if minutes <= DUP_WINDOW_HOURS * 60 and p.received_at <= candidate.received_at:
                f.duplicate_of = p.id
                f.minutes_apart = minutes
                f.flags.append(
                    "same_invoice_number" if inv and _norm_inv(p.invoice_number) == inv else "same_document"
                )
                if p.amount_cents == candidate.amount_cents:
                    f.flags.append("same_amount")
                break
    if f.duplicate_of is None and candidate.amount_cents < approval_limit_cents:
        for p in same_vendor:
            minutes = abs(int((candidate.received_at - p.received_at).total_seconds() // 60))
            if (
                minutes <= SPLIT_WINDOW_MINUTES
                and p.amount_cents < approval_limit_cents
                and _norm_inv(p.invoice_number) != inv
            ):
                total = p.amount_cents + candidate.amount_cents
                if total >= approval_limit_cents:
                    f.split_with.append(p.id)
                    f.minutes_apart = minutes if f.minutes_apart is None else min(f.minutes_apart, minutes)
                    f.combined_cents = (f.combined_cents or candidate.amount_cents) + p.amount_cents
                    f.under_limit_pattern = True
        if f.split_with:
            f.flags.append("split_under_approval_limit")
    return f
