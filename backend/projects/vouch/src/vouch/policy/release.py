"""Cedar-style payment policy on hm_agents_common.policy (default deny; any forbid beats any permit).

Deterministic sender check and vendor resolution feed two extra release rules (R_SENDER,
R_VENDOR_AMBIGUOUS); like every other hold they are resolved by the owner, never auto-denied.

Three actions:
- payment:release      may this card be paid at all?            forbid -> HOLD (never an automatic denial)
- payment:fast_pay     may it skip the owner's batch approval?  standing rule for verified small vendors
- payment:settle_batch may this batch hit the ledger?           owner approval + batch limit + kernel amounts

Every HOLD reason maps to a concrete resolution path (`REQUIRED_ACTIONS`), so a blocked honest vendor
always has a way through: out-of-band confirmation, owner review, or an appeal.
"""

from __future__ import annotations

from typing import Any

from hm_agents_common.policy import PolicyRequest, PolicySet, forbid, permit
from vouch.cards import PaymentCard
from vouch.domain import Lane, PolicyOutcome
from vouch.kernel import Limits

HIGH_RISK = 0.70  # a risk head at/above this ...
LOW_LEGITIMACY = 0.60  # ... with legitimacy below this is "high risk" on model evidence alone
FAST_PAY_MIN_LEGITIMACY = 0.85
FAST_PAY_MAX_RISK = 0.30

R_HIGH_RISK = "unresolved high fraud risk"
R_BANK = "bank details changed without out-of-band confirmation"
R_LIMIT = "amount exceeds the single-payment limit"
R_LLM_AMOUNT = "amount not verified by the deterministic kernel (missing or LLM-originated)"
R_LINES = "line items do not add up to the invoice total"
R_DUPLICATE = "possible duplicate invoice"
R_SPLIT = "possible split invoices under the approval limit"
R_RING = "vendor shares bank account or tax id with other vendors"
R_INJECTION = "invoice text contains instructions aimed at the payment system"
R_UNKNOWN_VENDOR = "vendor is not on the master file"
R_VENDOR_AMBIGUOUS = "vendor could not be matched unambiguously to the master file"
R_SENDER = "invoice email failed sender checks (authentication, lookalike domain or reply-to mismatch)"
R_OWNER_HOLD = "owner placed a hold"
R_NOTHING = "nothing payable after credit notes"
R_KICKBACK = "submission could not be read; a kickback email to the sender awaits the owner's approval"
R_OCR_UNAVAILABLE = (
    "image invoice could not be read: this server has no OCR engine (tesseract-ocr is not installed), "
    "so the attachment was never OCRed"
)
R_INTAKE_REVIEW = (
    "intake routing was ambiguous and no classifier answer passed validation; owner confirms the document"
)

REQUIRED_ACTIONS = {
    R_HIGH_RISK: "owner reviews the evidence and resolves the risk with a note (or the vendor appeals)",
    R_BANK: "confirm the bank change by calling the vendor at the phone number already on file",
    R_LIMIT: "owner approves a one-time limit override",
    R_LLM_AMOUNT: "re-key the amount from the source document (the kernel must parse it)",
    R_DUPLICATE: "owner confirms this is not a duplicate payment",
    R_SPLIT: "owner confirms the invoices are separate purchases (or asks for one combined invoice)",
    R_RING: "verify vendor identity out-of-band (tax id match, call-back, onboarding documents)",
    R_INJECTION: "owner reviews the invoice text; the vendor re-sends a clean invoice",
    R_UNKNOWN_VENDOR: "onboard the vendor (identity + bank verification) before paying",
    R_VENDOR_AMBIGUOUS: "owner picks the matching vendor record (or onboards a new vendor)",
    R_SENDER: "confirm the invoice with the vendor through a channel already on file; ask for a re-send from the registered address",
    R_OWNER_HOLD: "owner releases the hold",
    R_NOTHING: "no payment needed; credit carried forward",
    R_LINES: "owner checks the line items; the vendor re-issues a corrected invoice",
    R_KICKBACK: "owner approves the kickback email asking the sender for a readable invoice (or re-keys it from the original)",
    R_OCR_UNAVAILABLE: "install tesseract-ocr + tesseract-ocr-eng on the app server (/v1/health shows ocr.state) and resubmit the image, or re-key the invoice from the original",
    R_INTAKE_REVIEW: "owner confirms which document is the invoice and resolves with a note (or asks the sender for one invoice per email)",
}


def _c(req: PolicyRequest, key: str, default: Any = None) -> Any:
    return req.context.get(key, default)


def build_policy(limits: Limits) -> PolicySet:
    resolved = lambda r: bool(_c(r, "risk_resolved"))  # noqa: E731
    return PolicySet(
        [
            # -- release ---------------------------------------------------------------------------
            permit(
                action="payment:release",
                when=lambda r: bool(_c(r, "vendor_found")),
                description="known vendor with a kernel-computed amount",
            ),
            # First so it heads the card's reasons: an image the server could not OCR is a deployment fault
            # that explains every downstream "missing" below it (vendor, amount, nothing payable).
            forbid(
                action="payment:release",
                when=lambda r: _c(r, "ocr_unavailable") and not resolved(r),
                description=R_OCR_UNAVAILABLE,
            ),
            forbid(
                action="payment:release",
                when=lambda r: not _c(r, "vendor_found"),
                description=R_UNKNOWN_VENDOR,
            ),
            forbid(
                action="payment:*", when=lambda r: not _c(r, "amount_origin_ok"), description=R_LLM_AMOUNT
            ),
            forbid(
                action="payment:release",
                when=lambda r: _c(r, "vendor_ambiguous") and not resolved(r),
                description=R_VENDOR_AMBIGUOUS,
            ),
            forbid(
                action="payment:release",
                when=lambda r: _c(r, "sender_suspicious") and not resolved(r),
                description=R_SENDER,
            ),
            forbid(
                action="payment:release",
                when=lambda r: _c(r, "bank_unconfirmed") and not _c(r, "bank_confirmed"),
                description=R_BANK,
            ),
            forbid(
                action="payment:release",
                when=lambda r: (
                    _c(r, "payable_cents", 0) > limits.single_payment_limit_cents
                    and not _c(r, "limit_override")
                ),
                description=R_LIMIT,
            ),
            forbid(
                action="payment:release",
                when=lambda r: _c(r, "duplicate") and not resolved(r),
                description=R_DUPLICATE,
            ),
            forbid(
                action="payment:release",
                when=lambda r: _c(r, "split") and not resolved(r),
                description=R_SPLIT,
            ),
            forbid(
                action="payment:release", when=lambda r: _c(r, "ring") and not resolved(r), description=R_RING
            ),
            forbid(
                action="payment:release",
                when=lambda r: _c(r, "injection") and not resolved(r),
                description=R_INJECTION,
            ),
            forbid(
                action="payment:release",
                when=lambda r: _c(r, "lines_mismatch") and not resolved(r),
                description=R_LINES,
            ),
            forbid(action="payment:release", when=lambda r: _c(r, "owner_hold"), description=R_OWNER_HOLD),
            forbid(
                action="payment:release", when=lambda r: _c(r, "payable_cents", 0) <= 0, description=R_NOTHING
            ),
            # Advisory intake routing may only add friction: an unreadable submission is held (never denied)
            # until the owner approves the kickback email or re-keys the invoice from the original.
            forbid(
                action="payment:release",
                when=lambda r: _c(r, "intake_kickback") and not resolved(r),
                description=R_KICKBACK,
            ),
            # Safe default of the decision classifiers: an ambiguous route that no validated model answer
            # confirmed is a guess, and a guess is never paid; the owner confirms the document first.
            forbid(
                action="payment:release",
                when=lambda r: _c(r, "intake_review") and not resolved(r),
                description=R_INTAKE_REVIEW,
            ),
            forbid(
                action="payment:release",
                when=lambda r: _c(r, "high_risk") and not resolved(r),
                description=R_HIGH_RISK,
            ),
            # -- fast pay (standing owner rule) -------------------------------------------------------
            permit(
                action="payment:fast_pay",
                when=lambda r: (
                    _c(r, "legitimacy", 0) >= FAST_PAY_MIN_LEGITIMACY
                    and _c(r, "max_risk", 1) < FAST_PAY_MAX_RISK
                    and 0 < _c(r, "payable_cents", 0) <= limits.fast_pay_limit_cents
                    and _c(r, "verified_vendor")
                ),
                description="verified small vendor under the fast-pay limit",
            ),
            forbid(
                action="payment:fast_pay",
                when=lambda r: _c(r, "bank_change_recent"),
                description="any recent bank change goes through the owner",
            ),
            forbid(
                action="payment:fast_pay",
                when=lambda r: bool(_c(r, "flags")),
                description="card has kernel flags",
            ),
            # -- settle batch -------------------------------------------------------------------------
            permit(
                action="payment:settle_batch",
                when=lambda r: _c(r, "owner_approved") or _c(r, "fast_pay_only"),
                description="owner approved the batch (or fast-pay standing rule)",
            ),
            forbid(
                action="payment:settle_batch",
                when=lambda r: _c(r, "batch_total_cents", 0) > limits.batch_limit_cents,
                description="batch total exceeds the daily batch limit",
            ),
            forbid(
                action="payment:settle_batch",
                when=lambda r: not _c(r, "all_cards_released"),
                description="batch contains a card the release policy does not allow",
            ),
        ]
    )


def card_context(card: PaymentCard) -> dict[str, Any]:
    ch = card.checks
    s = card.scores
    max_risk = max(s.risk.values()) if s else 1.0
    legitimacy = s.legitimacy if s else 0.0
    vendor = card.vendor
    return {
        "vendor_found": vendor is not None,
        "amount_origin_ok": card.invoice.amount_origin in ("source", "kernel"),
        "payable_cents": card.payable_cents,
        "max_risk": max_risk,
        "legitimacy": legitimacy,
        "high_risk": max_risk >= HIGH_RISK and legitimacy < LOW_LEGITIMACY,
        "bank_unconfirmed": bool(ch.get("bank_mismatch"))
        or (bool(ch.get("bank_change_recent")) and not ch.get("bank_change_confirmed")),
        "bank_change_recent": bool(ch.get("bank_change_recent")) or bool(ch.get("bank_mismatch")),
        "bank_confirmed": card.has_resolution("confirm_bank"),
        "duplicate": bool(ch.get("duplicate_of")),
        "split": bool(ch.get("split_group")),
        "ring": bool(set(ch.get("shared_attributes", {})) & {"bank", "tax_id"}),
        "injection": bool(ch.get("injection")),
        "vendor_ambiguous": bool(card.resolution and card.resolution.status == "uncertain"),
        "sender_suspicious": bool(card.sender and card.sender.suspicious),
        "lines_mismatch": ch.get("line_items_match") is False,
        "risk_resolved": card.has_resolution("resolve_risk"),
        "limit_override": card.has_resolution("limit_override"),
        "owner_hold": _owner_hold_active(card),
        "intake_kickback": bool(card.intake and card.intake.kickback),
        "intake_review": bool(card.intake and card.intake.review_required),
        "ocr_unavailable": bool(card.intake and card.intake.ocr_unavailable),
        "verified_vendor": bool(vendor and (vendor.oob_verified or len(vendor.history) >= 3)),
        "flags": card.flags,
    }


def _owner_hold_active(card: PaymentCard) -> bool:
    state = False
    for r in card.resolutions:
        if r.kind == "owner_hold":
            state = True
        elif r.kind == "release_hold":
            state = False
    return state


def evaluate_card(policy: PolicySet, card: PaymentCard) -> PolicyOutcome:
    ctx = card_context(card)
    release = policy.evaluate(PolicyRequest("vouch", "payment:release", card.id, ctx))
    if not release.allowed:
        reasons = release.reasons
        return PolicyOutcome(
            lane=Lane.HOLD,
            allowed=False,
            reasons=reasons,
            required_actions=[REQUIRED_ACTIONS.get(r, "owner review") for r in reasons],
        )
    fast = policy.evaluate(PolicyRequest("vouch", "payment:fast_pay", card.id, ctx))
    if fast.allowed:
        return PolicyOutcome(lane=Lane.FAST_PAY, allowed=True, reasons=fast.reasons)
    reasons = ["passes release policy; waits for the owner's batch approval"]
    if card.flags:
        reasons.append("kernel notes: " + "; ".join(card.flags))
    return PolicyOutcome(lane=Lane.STANDARD, allowed=True, reasons=reasons)


def evaluate_batch(
    policy: PolicySet, cards: list[PaymentCard], owner_approved: bool, fast_pay_only: bool = False
):
    released = [evaluate_card(policy, c).allowed for c in cards]
    ctx = {
        "owner_approved": owner_approved,
        "fast_pay_only": fast_pay_only,
        "batch_total_cents": sum(c.payable_cents for c in cards),
        "all_cards_released": all(released),
        "amount_origin_ok": all(c.invoice.amount_origin in ("source", "kernel") for c in cards),
    }
    return policy.evaluate(PolicyRequest("vouch", "payment:settle_batch", "batch", ctx))
