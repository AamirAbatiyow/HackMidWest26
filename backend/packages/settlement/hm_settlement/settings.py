from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr

from hm_core.config import HMSettings


class SettlementSettings(HMSettings):
    settlement_adapter: Literal["mock", "xrpl", "arc"] = "mock"

    xrpl_network_url: str = "https://s.altnet.rippletest.net:51234"
    xrpl_wallet_seed: SecretStr = SecretStr("")
    xrpl_destination_address: str = ""
    # IOU / issued-currency settings (stablecoin-style token on testnet).
    # The issuer is the account that issued the token; receivers must have a trustline to it.
    # Currency code: 3-char ISO (USD, EUR) or 40-hex for longer codes (RLUSD = 524C555344...).
    xrpl_iou_issuer: str = ""
    xrpl_iou_currency: str = "USD"
    # When true, payments use the IOU; when false or issuer is empty, falls back to XRP drops.
    xrpl_use_iou: bool = True
    # Testnet demo scaling: invoices are in USD, testnet faucets hand out ~100 XRP.
    # 0.0001 XRP per USD means a $48,000 batch moves 4.8 test XRP. Only used for XRP fallback.
    xrpl_xrp_per_usd: Decimal = Decimal("0.0001")
    # Use the XLS-56 Batch transaction (all-or-nothing) for multi-payment batches when available.
    xrpl_use_batch: bool = True
    xrpl_explorer_url: str = "https://testnet.xrpl.org/transactions/"

    arc_rpc_url: str = ""
    arc_chain_id: int | None = None
    arc_private_key: SecretStr = SecretStr("")
    arc_usdc_contract: str = ""
    arc_explorer_url: str = ""


@lru_cache
def get_settlement_settings() -> SettlementSettings:
    return SettlementSettings()
