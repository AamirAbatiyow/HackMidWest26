from functools import lru_cache

from hm_settlement.base import SettlementAdapter
from hm_settlement.mock import MockSettlementAdapter
from hm_settlement.models import PaymentReceipt, PaymentRequest, PaymentStatus, Quote
from hm_settlement.settings import SettlementSettings, get_settlement_settings


def make_adapter(name: str | None = None) -> SettlementAdapter:
    """Build an adapter by name (default: SETTLEMENT_ADAPTER env, which defaults to `mock`)."""
    name = name or get_settlement_settings().settlement_adapter
    if name == "mock":
        return MockSettlementAdapter()
    if name == "xrpl":
        from hm_settlement.xrpl_adapter import XRPLTestnetAdapter

        return XRPLTestnetAdapter()
    if name == "arc":
        from hm_settlement.arc_adapter import ArcUSDCAdapter

        return ArcUSDCAdapter()
    raise ValueError(f"unknown settlement adapter: {name}")


@lru_cache
def get_adapter() -> SettlementAdapter:
    """Process-wide adapter (keeps mock-ledger state across requests)."""
    return make_adapter()


__all__ = [
    "MockSettlementAdapter",
    "PaymentReceipt",
    "PaymentRequest",
    "PaymentStatus",
    "Quote",
    "SettlementAdapter",
    "SettlementSettings",
    "get_adapter",
    "get_settlement_settings",
    "make_adapter",
]
