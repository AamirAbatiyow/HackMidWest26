"""Policy engine: Cedar (via cedarpy) with a Python mirror of the same rules as fallback.

The mirror exists so the backend runs where the Rust wheel is unavailable; a test asserts
both engines agree on a fixture matrix. Default is DENY in both.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from ..config import POLICY_DIR
from ..models import PolicyResult

log = logging.getLogger(__name__)

RULES: dict[str, str] = {
    "P-01": "Owner approves payments; model output never approves or moves money",
    "P-02": "Owner may hold or vouch; nothing is ever auto-denied",
    "P-03": "Automated checks may only place a hold",
    "P-04": "Fast pay only for vouched, eligible payments with no unverified bank change",
    "P-05": "Settlement requires a recorded owner approval",
    "P-06": "Bank changes require owner call-back verification",
    "P-07": "Model may read and explain; explanations carry no authority",
    "DEFAULT-DENY": "No matching permit: denied by default (fees, rounding, amount edits, denials, model actions)",
}

AUTOMATED_ACTIONS = ["fast_pay", "hold", "deny_vendor", "add_fee", "round_amount", "modify_amount", "settle"]
MODEL_ACTIONS = [
    "approve",
    "settle",
    "fast_pay",
    "deny_vendor",
    "modify_amount",
    "change_bank_details",
    "explain",
]


@dataclass
class PaymentAttrs:
    status: str
    lifecycle: str
    risk: str
    trust_score: int
    fast_pay_eligible: bool
    bank_changed: bool
    bank_change_verified: bool
    amount_cents: int
    vendor_known: bool


@dataclass
class AuthzOutcome:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    engine: str = "python-mirror"


def _cedar_entities(payment_id: str, attrs: PaymentAttrs) -> list[dict[str, Any]]:
    return [
        {
            "uid": {"type": "Payment", "id": payment_id},
            "attrs": {
                "status": attrs.status,
                "lifecycle": attrs.lifecycle,
                "risk": attrs.risk,
                "trust_score": attrs.trust_score,
                "fast_pay_eligible": attrs.fast_pay_eligible,
                "bank_changed": attrs.bank_changed,
                "bank_change_verified": attrs.bank_change_verified,
                "amount_cents": attrs.amount_cents,
                "vendor_known": attrs.vendor_known,
            },
            "parents": [],
        },
        {"uid": {"type": "Owner", "id": "owner"}, "attrs": {}, "parents": []},
        {"uid": {"type": "System", "id": "vouch"}, "attrs": {}, "parents": []},
        {"uid": {"type": "Model", "id": "model"}, "attrs": {}, "parents": []},
    ]


@lru_cache(maxsize=1)
def policy_text() -> str:
    return (POLICY_DIR / "vouch.cedar").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def policy_ids() -> list[str]:
    """``@id("P-xx")`` annotations in file order; Cedar reports policies as policy0, policy1…"""
    import re

    return re.findall(r'@id\("([^"]+)"\)', policy_text())


def _reason_to_id(reason: str) -> str:
    if reason.startswith("policy") and reason[6:].isdigit():
        idx = int(reason[6:])
        ids = policy_ids()
        if idx < len(ids):
            return ids[idx]
    return reason


@lru_cache(maxsize=1)
def cedar_available() -> bool:
    try:
        import cedarpy

        probe = cedarpy.is_authorized(
            {
                "principal": 'Owner::"owner"',
                "action": 'Action::"read"',
                "resource": 'Payment::"probe"',
                "context": {},
            },
            policy_text(),
            [],
        )
        if str(probe.decision).endswith("NoDecision"):
            log.error("cedar policy failed to parse: %s", probe.diagnostics.errors)
            return False
        return True
    except Exception as exc:
        log.info("cedarpy unavailable (%s); using python mirror", exc)
        return False


def _mirror(principal_type: str, action: str, attrs: PaymentAttrs, ctx: dict[str, Any]) -> AuthzOutcome:
    """Python mirror of policies/vouch.cedar. Keep in sync; test_policy checks parity."""
    if principal_type == "Owner":
        if action == "approve" and attrs.lifecycle in ("pending", "held", "appealed"):
            return AuthzOutcome(True, ["P-01"])
        if action in ("hold", "appeal") and attrs.lifecycle != "settled":
            return AuthzOutcome(True, ["P-02"])
        if action == "settle" and attrs.lifecycle == "approved" and ctx.get("owner_approval_recorded"):
            return AuthzOutcome(True, ["P-05"])
        if action == "change_bank_details" and ctx.get("callback_verified"):
            return AuthzOutcome(True, ["P-06"])
    if principal_type == "System":
        if action == "hold":
            return AuthzOutcome(True, ["P-03"])
        if (
            action == "fast_pay"
            and attrs.status == "vouched"
            and attrs.fast_pay_eligible
            and not (attrs.bank_changed and not attrs.bank_change_verified)
            and attrs.amount_cents <= int(ctx.get("approval_limit_cents", 0))
        ):
            return AuthzOutcome(True, ["P-04"])
        if action == "settle" and attrs.lifecycle == "approved" and ctx.get("owner_approval_recorded"):
            return AuthzOutcome(True, ["P-05"])
        if action in ("read", "explain"):
            return AuthzOutcome(True, ["P-07"])
    return AuthzOutcome(False, ["DEFAULT-DENY"])


def authorize(
    principal_type: str,
    action: str,
    attrs: PaymentAttrs,
    context: dict[str, Any] | None = None,
    *,
    payment_id: str = "payment",
) -> AuthzOutcome:
    """Default-deny authorization for one action on one payment."""
    ctx = {
        "approval_limit_cents": 0,
        "owner_approval_recorded": False,
        "callback_verified": False,
        **(context or {}),
    }
    principal_id = {"Owner": "owner", "System": "vouch", "Model": "model"}.get(
        principal_type, principal_type.lower()
    )
    if cedar_available():
        try:
            import cedarpy

            request = {
                "principal": f'{principal_type}::"{principal_id}"',
                "action": f'Action::"{action}"',
                "resource": f'Payment::"{payment_id}"',
                "context": ctx,
            }
            result = cedarpy.is_authorized(request, policy_text(), _cedar_entities(payment_id, attrs))
            decision = str(result.decision)
            if decision.endswith("NoDecision"):
                raise RuntimeError(f"cedar returned no decision: {result.diagnostics.errors}")
            allowed = decision.endswith("Allow")
            reasons = [_reason_to_id(r) for r in result.diagnostics.reasons] if allowed else ["DEFAULT-DENY"]
            return AuthzOutcome(allowed, reasons, engine="cedar")
        except Exception as exc:  # pragma: no cover - engine failure
            log.warning("cedar evaluation failed (%s); using python mirror", exc)
    return _mirror(principal_type, action, attrs, ctx)


def evaluate_payment(
    attrs: PaymentAttrs, approval_limit_cents: int, payment_id: str = "payment"
) -> PolicyResult:
    """What the automated system (and the model) may do with this payment right now."""
    ctx = {"approval_limit_cents": approval_limit_cents}
    allowed: list[str] = []
    denied: list[str] = []
    fired: list[str] = []
    engine = "python-mirror"
    for action in AUTOMATED_ACTIONS:
        out = authorize("System", action, attrs, ctx, payment_id=payment_id)
        engine = out.engine
        (allowed if out.allowed else denied).append(f"system:{action}")
        for r in out.reasons:
            if r not in fired:
                fired.append(r)
    for action in MODEL_ACTIONS:
        out = authorize("Model", action, attrs, ctx, payment_id=payment_id)
        (allowed if out.allowed else denied).append(f"model:{action}")
    if "DEFAULT-DENY" not in fired:
        fired.append("DEFAULT-DENY")
    return PolicyResult(
        engine=engine,  # type: ignore[arg-type]
        allowed_actions=allowed,
        denied_actions=denied,
        hold_recommended=attrs.status != "vouched",
        rules_fired=[f"{r} · {RULES.get(r, r)}" for r in fired],
    )
