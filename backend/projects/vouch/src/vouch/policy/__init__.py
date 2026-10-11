"""Two policy layers, both default deny:

- `release`: the Cedar-style PaymentCard policy (hm_agents_common.policy) that decides the lane
  (FAST_PAY / STANDARD / HOLD) and whether a batch may hit the ledger.
- `engine`: real Cedar (cedarpy, with a Python mirror of policies/vouch.cedar) that authorizes *who*
  may do *what*: the owner approves/holds/appeals, the system may only hold or fast-pay within the
  standing rule, and the model can never approve, settle, deny a vendor or touch an amount.
"""

from .engine import RULES, AuthzOutcome, PaymentAttrs, authorize, cedar_available, evaluate_payment
from .release import (
    FAST_PAY_MAX_RISK,
    FAST_PAY_MIN_LEGITIMACY,
    HIGH_RISK,
    LOW_LEGITIMACY,
    R_BANK,
    R_DUPLICATE,
    R_HIGH_RISK,
    R_INJECTION,
    R_LIMIT,
    R_LINES,
    R_LLM_AMOUNT,
    R_NOTHING,
    R_OWNER_HOLD,
    R_RING,
    R_SENDER,
    R_SPLIT,
    R_UNKNOWN_VENDOR,
    R_VENDOR_AMBIGUOUS,
    REQUIRED_ACTIONS,
    build_policy,
    card_context,
    evaluate_batch,
    evaluate_card,
)

__all__ = [
    "FAST_PAY_MAX_RISK",
    "FAST_PAY_MIN_LEGITIMACY",
    "HIGH_RISK",
    "LOW_LEGITIMACY",
    "REQUIRED_ACTIONS",
    "RULES",
    "AuthzOutcome",
    "PaymentAttrs",
    "R_BANK",
    "R_DUPLICATE",
    "R_HIGH_RISK",
    "R_INJECTION",
    "R_LIMIT",
    "R_LINES",
    "R_LLM_AMOUNT",
    "R_NOTHING",
    "R_OWNER_HOLD",
    "R_RING",
    "R_SENDER",
    "R_SPLIT",
    "R_UNKNOWN_VENDOR",
    "R_VENDOR_AMBIGUOUS",
    "authorize",
    "build_policy",
    "card_context",
    "cedar_available",
    "evaluate_batch",
    "evaluate_card",
    "evaluate_payment",
]
