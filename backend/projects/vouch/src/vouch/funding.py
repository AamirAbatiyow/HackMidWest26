"""Deterministic funding recommender: pay now vs. schedule, from a cash-forecast stub. Integer cents.

Rules, in order:
1. Fast-pay cards are paid now (small verified vendors get their money the same day).
2. Early-payment discount still open and cash stays above the buffer -> pay now and keep the discount.
3. Due within 2 days -> pay now if cash allows, else the first day the forecast covers it (flagged).
4. Otherwise schedule for the due date minus one day (never late), keeping cash working until then;
   if the forecast can't cover it by then, the first covering day (flagged as a shortfall).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from vouch.cards import PaymentCard
from vouch.domain import Lane
from vouch.kernel import format_cents


@dataclass
class CashForecast:
    opening_balance_cents: int = 18_500_000  # $185,000 operating account
    buffer_cents: int = 2_500_000  # never drop below $25,000
    receivables: list[tuple[int, int]] = field(
        default_factory=lambda: [(3, 4_200_000), (8, 6_100_000), (15, 3_800_000)]
    )  # (days from today, cents expected in)
    committed: list[tuple[int, int]] = field(
        default_factory=lambda: [(1, 1_900_000), (14, 2_600_000)]
    )  # payroll, rent

    def inflow_by(self, day: int) -> int:
        return sum(c for d, c in self.receivables if d <= day) - sum(c for d, c in self.committed if d <= day)

    def to_dict(self, today: date) -> dict[str, Any]:
        return {
            "opening_balance_cents": self.opening_balance_cents,
            "buffer_cents": self.buffer_cents,
            "receivables": [
                {"date": (today + timedelta(days=d)).isoformat(), "cents": c} for d, c in self.receivables
            ],
            "committed": [
                {"date": (today + timedelta(days=d)).isoformat(), "cents": c} for d, c in self.committed
            ],
        }


def discount_cents(card: PaymentCard, today: date) -> int:
    inv = card.invoice
    if inv.discount_bps <= 0 or today > inv.issue_date + timedelta(days=inv.discount_days):
        return 0
    return card.payable_cents * inv.discount_bps // 10_000


def recommend(cards: list[PaymentCard], forecast: CashForecast, today: date) -> dict[str, dict[str, Any]]:
    """Recommendation per card id. Only cards the policy allows are funded; holds are listed as waiting."""
    out: dict[str, dict[str, Any]] = {}
    scheduled: list[tuple[int, int]] = []  # (day offset, cents) already committed by earlier cards

    def cash_on(day: int) -> int:
        return (
            forecast.opening_balance_cents
            + forecast.inflow_by(day)
            - sum(c for d, c in scheduled if d <= day)
        )

    def first_covering_day(cents: int, start: int) -> int | None:
        for day in range(start, 61):
            if all(cash_on(d) - cents >= forecast.buffer_cents for d in range(day, 61)):
                return day
        return None

    order = sorted(
        cards, key=lambda c: (c.policy.lane != Lane.FAST_PAY if c.policy else True, c.invoice.due_date, c.id)
    )
    for card in order:
        if not card.policy or not card.policy.allowed:
            out[card.id] = {"action": "wait", "reason": "on hold until resolved", "pay_on": None}
            continue
        cents = card.payable_cents
        due = (card.invoice.due_date - today).days
        disc = discount_cents(card, today)
        rec: dict[str, Any]
        if card.policy.lane == Lane.FAST_PAY and cash_on(0) - cents >= forecast.buffer_cents:
            rec = {"action": "pay_now", "day": 0, "reason": "fast-pay lane: verified small vendor paid today"}
        elif disc and cash_on(0) - cents >= forecast.buffer_cents:
            rec = {
                "action": "pay_now",
                "day": 0,
                "discount_cents": disc,
                "reason": f"early-payment discount of {format_cents(disc)} is still open and cash stays above the buffer",
            }
        elif due <= 2:
            day = first_covering_day(cents, 0)
            rec = {
                "action": "pay_now" if day == 0 else "schedule",
                "day": day,
                "reason": "due within 2 days"
                + ("" if day == 0 else "; cash shortfall, paid on first covered day"),
                "shortfall": day != 0,
            }
        else:
            target = max(due - 1, 0)
            day = first_covering_day(cents, target)
            if day is None:
                day = target
            rec = {
                "action": "schedule",
                "day": day,
                "shortfall": day > target,
                "reason": "scheduled for the day before the due date; cash keeps working until then"
                if day == target
                else "cash shortfall: scheduled for the first day the forecast covers it",
            }
        if rec.get("day") is not None:
            scheduled.append((rec["day"], cents))
            rec["pay_on"] = (today + timedelta(days=rec["day"])).isoformat()
            rec["on_time"] = rec["day"] <= max(due, 0)
        rec.setdefault("discount_cents", 0)
        out[card.id] = rec
    return out
