"""USDC on Circle Arc testnet adapter (stub). Install with `uv sync --all-packages --group chain`.

Implementation notes for when this gets filled in (web3.py >= 7):
- TODO(confirm at the venue / Circle docs): Arc testnet RPC URL, chain id, USDC contract address,
  decimals, faucet, and explorer URL. All are read from env (ARC_*), nothing is hard-coded.
- Client: `Web3(Web3.HTTPProvider(settings.arc_rpc_url))`; account from `ARC_PRIVATE_KEY`
  via `w3.eth.account.from_key(...)` (testnet key only; never commit).
- Transfer: ERC-20 `transfer(to, amount * 10**decimals)` using a minimal ABI; sign with the account,
  `send_raw_transaction`, then `wait_for_transaction_receipt`; status==1 -> SETTLED.
- Idempotency: persist idempotency_key -> tx hash before broadcasting; on retry, look it up first.
- Milestone hold/release would need an escrow contract; out of scope unless the concept requires it.
"""

from __future__ import annotations

from hm_settlement.base import SettlementAdapter
from hm_settlement.models import PaymentReceipt, PaymentRequest, PaymentStatus, Quote
from hm_settlement.settings import SettlementSettings, get_settlement_settings

ERC20_TRANSFER_ABI = [
    {
        "name": "transfer",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "decimals",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint8"}],
    },
]


class ArcUSDCAdapter(SettlementAdapter):
    name = "arc"
    network = "arc-testnet"

    def __init__(self, settings: SettlementSettings | None = None) -> None:
        self.settings = settings or get_settlement_settings()
        # TODO: self.w3 = Web3(Web3.HTTPProvider(self.settings.arc_rpc_url))
        # TODO: self.account = self.w3.eth.account.from_key(self.settings.arc_private_key.get_secret_value())
        # TODO: self.usdc = self.w3.eth.contract(address=..., abi=ERC20_TRANSFER_ABI)

    def quote(self, request: PaymentRequest) -> Quote:
        # TODO: estimate_gas on transfer() * gas price; report fee in the native gas unit.
        raise NotImplementedError("ArcUSDCAdapter.quote")

    def send(self, request: PaymentRequest) -> PaymentReceipt:
        # TODO: build+sign ERC-20 transfer, broadcast, wait for receipt, map -> PaymentReceipt.
        raise NotImplementedError("ArcUSDCAdapter.send")

    def get_status(self, tx_id: str) -> PaymentStatus:
        # TODO: w3.eth.get_transaction_receipt(tx_id); missing -> PENDING, status 1 -> SETTLED, 0 -> FAILED.
        raise NotImplementedError("ArcUSDCAdapter.get_status")

    def explorer_url(self, tx_id: str) -> str | None:
        # TODO: set ARC_EXPLORER_URL once the official testnet explorer is confirmed.
        base = self.settings.arc_explorer_url
        return f"{base.rstrip('/')}/tx/{tx_id}" if base else None
