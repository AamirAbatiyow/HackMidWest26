"""Settlement adapter interface. Agents/tools depend on this, never on a specific chain SDK."""

from __future__ import annotations

from abc import ABC, abstractmethod

from hm_settlement.models import PaymentReceipt, PaymentRequest, PaymentStatus, Quote


class SettlementAdapter(ABC):
    name: str = "base"
    network: str = "unknown"

    @abstractmethod
    def quote(self, request: PaymentRequest) -> Quote:
        """Estimate fees / converted amount without moving funds."""

    @abstractmethod
    def send(self, request: PaymentRequest) -> PaymentReceipt:
        """Move funds. MUST be idempotent on `request.idempotency_key`.

        Call only after human approval (see hm_agents_common.approval) for anything non-trivial.
        """

    def send_batch(self, requests: list[PaymentRequest], atomic: bool = True) -> list[PaymentReceipt]:
        """Pay several destinations. Default: sequential `send`. Chain adapters override with a native
        batch (e.g. XRPL Batch with all-or-nothing semantics) when they can guarantee atomicity."""
        return [self.send(r) for r in requests]

    @abstractmethod
    def get_status(self, tx_id: str) -> PaymentStatus:
        """Look up the current status of a previously sent payment."""

    def verify(self, receipt: PaymentReceipt) -> bool:
        """Independently confirm a receipt on the ledger. Default: status lookup."""
        return self.get_status(receipt.tx_id) == PaymentStatus.SETTLED

    def explorer_url(self, tx_id: str) -> str | None:
        """Public explorer link for the demo (judges love clicking a real tx)."""
        return None

    # Optional conditional-payment primitives (e.g. milestone escrow). Override if the concept needs them.
    def hold(self, request: PaymentRequest) -> PaymentReceipt:
        raise NotImplementedError(f"{self.name} does not support hold/escrow")

    def release(self, tx_id: str) -> PaymentReceipt:
        raise NotImplementedError(f"{self.name} does not support hold/escrow")

    def cancel(self, tx_id: str) -> PaymentReceipt:
        raise NotImplementedError(f"{self.name} does not support cancel")
