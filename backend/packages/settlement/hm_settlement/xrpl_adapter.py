"""XRPL testnet adapter (xrpl-py). Install with `uv sync --all-packages --group chain`.

- One funded source wallet (XRPL_WALLET_SEED, never committed) pays out.
- Destinations: a classic r-address in `PaymentRequest.destination`, or the shared demo receiving
  account XRPL_DESTINATION_ADDRESS plus a per-payee `destination_tag` from `request.metadata`.
- USD amounts are scaled to test XRP with XRPL_XRP_PER_USD (demo only; testnet XRP has no value).
- `send_batch` submits up to 8 payments as one XLS-56 `Batch` transaction with tfAllOrNothing: either
  every vendor in the chunk is paid or none is. Each inner payment gets its own ledger hash.
- Idempotency: the key is written into a Memo and kept in a local key -> receipt map, so retries in the
  same process never double-pay. (A production system would persist this map before submitting.)

Get funded testnet wallets with `python -m hm_settlement.xrpl_setup`.
"""

from __future__ import annotations

import threading
import time
from decimal import ROUND_DOWN, Decimal
from typing import Any

from hm_core.errors import ConfigError, UpstreamError
from hm_settlement.base import SettlementAdapter
from hm_settlement.models import PaymentReceipt, PaymentRequest, PaymentStatus, Quote
from hm_settlement.settings import SettlementSettings, get_settlement_settings

MAX_BATCH_INNER = 8
_DROPS_PER_XRP = Decimal(1_000_000)


def _is_classic_address(value: str) -> bool:
    return value.startswith("r") and 25 <= len(value) <= 35


class XRPLTestnetAdapter(SettlementAdapter):
    name = "xrpl"
    network = "xrpl-testnet"

    def __init__(self, settings: SettlementSettings | None = None, client: Any = None, wallet: Any = None):
        try:
            from xrpl.clients import JsonRpcClient
            from xrpl.wallet import Wallet
        except ImportError as exc:  # pragma: no cover - depends on installed extras
            raise ConfigError("xrpl-py is not installed: `uv sync --all-packages --group chain`") from exc
        self.settings = settings or get_settlement_settings()
        self.client = client or JsonRpcClient(self.settings.xrpl_network_url)
        seed = self.settings.xrpl_wallet_seed.get_secret_value()
        if wallet is None and not seed:
            raise ConfigError(
                "XRPL_WALLET_SEED is empty: run `python -m hm_settlement.xrpl_setup --write-env` "
                "to create funded testnet wallets"
            )
        self.wallet = wallet or Wallet.from_seed(seed)
        self._by_key: dict[str, PaymentReceipt] = {}
        self._lock = threading.Lock()

    # -- helpers -----------------------------------------------------------------------------------

    def to_drops(self, request: PaymentRequest) -> str:
        amount = request.amount
        if request.currency.upper() != "XRP":
            amount = amount * self.settings.xrpl_xrp_per_usd
        drops = (amount * _DROPS_PER_XRP).quantize(Decimal(1), rounding=ROUND_DOWN)
        if drops <= 0:
            raise ValueError(f"amount {request.amount} {request.currency} scales to 0 drops")
        return str(int(drops))

    def _destination(self, request: PaymentRequest) -> tuple[str, int | None]:
        tag = request.metadata.get("destination_tag")
        tag = int(tag) if tag is not None else None
        if _is_classic_address(request.destination):
            return request.destination, tag
        if not self.settings.xrpl_destination_address:
            raise ConfigError(
                f"destination {request.destination!r} is not an XRPL address and XRPL_DESTINATION_ADDRESS is empty"
            )
        return self.settings.xrpl_destination_address, tag

    def _payment(self, request: PaymentRequest, **extra: Any) -> Any:
        from xrpl.models.transactions import Memo, Payment

        destination, tag = self._destination(request)
        memo_text = f"{request.idempotency_key}|{request.memo or ''}"[:250]
        return Payment(
            account=self.wallet.classic_address,
            destination=destination,
            destination_tag=tag,
            amount=self.to_drops(request),
            memos=[Memo(memo_type=b"vouch/idempotency".hex(), memo_data=memo_text.encode().hex())],
            **extra,
        )

    def _receipt(
        self, request: PaymentRequest, tx_hash: str, ok: bool, raw: dict[str, Any]
    ) -> PaymentReceipt:
        receipt = PaymentReceipt(
            tx_id=tx_hash,
            status=PaymentStatus.SETTLED if ok else PaymentStatus.FAILED,
            network=self.network,
            amount=request.amount,
            currency=request.currency,
            destination=request.destination,
            idempotency_key=request.idempotency_key,
            explorer_url=self.explorer_url(tx_hash),
            raw=raw,
        )
        if ok:
            self._by_key[request.idempotency_key] = receipt
        return receipt

    # -- interface ---------------------------------------------------------------------------------

    def quote(self, request: PaymentRequest) -> Quote:
        from xrpl.ledger import get_fee

        fee_drops = Decimal(get_fee(self.client))
        return Quote(
            amount=Decimal(self.to_drops(request)) / _DROPS_PER_XRP,
            currency="XRP",
            network_fee=fee_drops / _DROPS_PER_XRP,
            network=self.network,
        )

    def send(self, request: PaymentRequest) -> PaymentReceipt:
        from xrpl.transaction import submit_and_wait

        with self._lock:
            if request.idempotency_key in self._by_key:
                return self._by_key[request.idempotency_key]
            try:
                result = submit_and_wait(self._payment(request), self.client, self.wallet).result
            except Exception as exc:
                raise UpstreamError(f"XRPL payment failed: {exc}") from exc
            ok = result.get("meta", {}).get("TransactionResult") == "tesSUCCESS"
            raw = {
                "engine_result": result.get("meta", {}).get("TransactionResult"),
                "ledger_index": result.get("ledger_index"),
            }
            return self._receipt(request, result["hash"], ok, raw)

    def send_batch(self, requests: list[PaymentRequest], atomic: bool = True) -> list[PaymentReceipt]:
        with self._lock:
            done = {
                r.idempotency_key: self._by_key[r.idempotency_key]
                for r in requests
                if r.idempotency_key in self._by_key
            }
            todo = [r for r in requests if r.idempotency_key not in done]
        if not todo:
            return [done[r.idempotency_key] for r in requests]
        if not self.settings.xrpl_use_batch or len(todo) == 1:
            for r in todo:
                done[r.idempotency_key] = self.send(r)
            return [done[r.idempotency_key] for r in requests]
        for start in range(0, len(todo), MAX_BATCH_INNER):
            chunk = todo[start : start + MAX_BATCH_INNER]
            for receipt in self._submit_batch(chunk, atomic):
                done[receipt.idempotency_key] = receipt
        return [done[r.idempotency_key] for r in requests]

    def _submit_batch(self, chunk: list[PaymentRequest], atomic: bool) -> list[PaymentReceipt]:
        from xrpl.account import get_next_valid_seq_number
        from xrpl.models.transactions import Batch
        from xrpl.models.transactions.batch import BatchFlag
        from xrpl.transaction import submit_and_wait

        with self._lock:
            try:
                seq = get_next_valid_seq_number(self.wallet.classic_address, self.client)
                inner = [
                    self._payment(r, sequence=seq + 1 + i, fee="0", signing_pub_key="")
                    for i, r in enumerate(chunk)
                ]
                flag = BatchFlag.TF_ALL_OR_NOTHING if atomic else BatchFlag.TF_INDEPENDENT
                batch = Batch(
                    account=self.wallet.classic_address, raw_transactions=inner, flags=flag, sequence=seq
                )
                result = submit_and_wait(batch, self.client, self.wallet).result
            except Exception as exc:
                raise UpstreamError(f"XRPL batch failed: {exc}") from exc
            batch_hash = result["hash"]
            outer_ok = result.get("meta", {}).get("TransactionResult") == "tesSUCCESS"
            inner_results = self._inner_results(batch_hash, len(chunk)) if outer_ok else {}
            receipts = []
            for i, request in enumerate(chunk):
                tx_hash, engine = inner_results.get(seq + 1 + i, (batch_hash, "unknown"))
                ok = outer_ok and engine == "tesSUCCESS"
                raw = {
                    "batch_hash": batch_hash,
                    "batch_explorer_url": self.explorer_url(batch_hash),
                    "engine_result": engine,
                    "atomic": atomic,
                }
                receipts.append(self._receipt(request, tx_hash, ok, raw))
            return receipts

    def _inner_results(self, batch_hash: str, expected: int, attempts: int = 6) -> dict[int, tuple[str, str]]:
        """Map inner Sequence -> (hash, engine result) for payments applied by `batch_hash`."""
        from xrpl.models.requests import AccountTx

        found: dict[int, tuple[str, str]] = {}
        for attempt in range(attempts):
            txs = self.client.request(AccountTx(account=self.wallet.classic_address, limit=40)).result.get(
                "transactions", []
            )
            for entry in txs:
                if entry.get("meta", {}).get("ParentBatchID") != batch_hash:
                    continue
                tx = entry.get("tx_json") or entry.get("tx") or {}
                found[int(tx.get("Sequence", -1))] = (entry["hash"], entry["meta"]["TransactionResult"])
            if len(found) >= expected:
                break
            time.sleep(1 + attempt)
        return found

    def get_status(self, tx_id: str) -> PaymentStatus:
        from xrpl.models.requests import Tx

        result = self.client.request(Tx(transaction=tx_id)).result
        if result.get("error") == "txnNotFound":
            return PaymentStatus.PENDING
        if not result.get("validated"):
            return PaymentStatus.PENDING
        engine = result.get("meta", {}).get("TransactionResult")
        return PaymentStatus.SETTLED if engine == "tesSUCCESS" else PaymentStatus.FAILED

    def explorer_url(self, tx_id: str) -> str | None:
        return f"{self.settings.xrpl_explorer_url.rstrip('/')}/{tx_id}"
