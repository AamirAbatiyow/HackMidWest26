"""In-memory adapter: the default so demos work end-to-end before any chain integration."""

from __future__ import annotations

import threading
import uuid

from hm_core.errors import NotFoundError
from hm_settlement.base import SettlementAdapter
from hm_settlement.models import PaymentReceipt, PaymentRequest, PaymentStatus, Quote


class MockSettlementAdapter(SettlementAdapter):
    name = "mock"
    network = "mock-ledger"

    def __init__(self) -> None:
        self._by_tx: dict[str, PaymentReceipt] = {}
        self._by_key: dict[str, str] = {}
        self._lock = threading.Lock()

    def quote(self, request: PaymentRequest) -> Quote:
        return Quote(amount=request.amount, currency=request.currency, network=self.network)

    def _record(self, request: PaymentRequest, status: PaymentStatus) -> PaymentReceipt:
        with self._lock:
            if request.idempotency_key in self._by_key:
                return self._by_tx[self._by_key[request.idempotency_key]]
            tx_id = f"mock_{uuid.uuid4().hex[:16]}"
            receipt = PaymentReceipt(
                tx_id=tx_id,
                status=status,
                network=self.network,
                amount=request.amount,
                currency=request.currency,
                destination=request.destination,
                idempotency_key=request.idempotency_key,
                explorer_url=self.explorer_url(tx_id),
            )
            self._by_tx[tx_id] = receipt
            self._by_key[request.idempotency_key] = tx_id
            return receipt

    def send(self, request: PaymentRequest) -> PaymentReceipt:
        return self._record(request, PaymentStatus.SETTLED)

    def hold(self, request: PaymentRequest) -> PaymentReceipt:
        return self._record(request, PaymentStatus.HELD)

    def _transition(self, tx_id: str, frm: PaymentStatus, to: PaymentStatus) -> PaymentReceipt:
        with self._lock:
            receipt = self._by_tx.get(tx_id)
            if receipt is None:
                raise NotFoundError(f"unknown tx {tx_id}")
            if receipt.status != frm:
                raise ValueError(f"tx {tx_id} is {receipt.status}, expected {frm}")
            receipt = receipt.model_copy(update={"status": to})
            self._by_tx[tx_id] = receipt
            return receipt

    def release(self, tx_id: str) -> PaymentReceipt:
        return self._transition(tx_id, PaymentStatus.HELD, PaymentStatus.SETTLED)

    def cancel(self, tx_id: str) -> PaymentReceipt:
        return self._transition(tx_id, PaymentStatus.HELD, PaymentStatus.CANCELLED)

    def get_status(self, tx_id: str) -> PaymentStatus:
        receipt = self._by_tx.get(tx_id)
        if receipt is None:
            raise NotFoundError(f"unknown tx {tx_id}")
        return receipt.status
