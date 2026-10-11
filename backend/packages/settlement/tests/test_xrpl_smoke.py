"""Opt-in live XRPL testnet smoke test.

Run with: `make xrpl-smoke` (requires XRPL_WALLET_SEED from `make xrpl-wallets`).

This test actually sends transactions to the XRPL testnet. It is skipped by default
when XRPL_WALLET_SEED is not set so CI never hits the network.
"""

import os
from decimal import Decimal

import pytest

from hm_settlement import PaymentRequest, PaymentStatus
from hm_settlement.settings import get_settlement_settings

pytestmark = pytest.mark.skipif(
    not os.environ.get("XRPL_WALLET_SEED"),
    reason="XRPL_WALLET_SEED not set; run `make xrpl-wallets` first",
)


@pytest.fixture
def xrpl_adapter():
    """Create a real XRPL adapter with testnet configuration."""
    pytest.importorskip("xrpl")
    from hm_settlement.xrpl_adapter import XRPLTestnetAdapter

    return XRPLTestnetAdapter()


def test_xrpl_live_single_payment(xrpl_adapter):
    """Send a real payment on the XRPL testnet."""
    settings = get_settlement_settings()
    amount = Decimal("0.01")  # small amount for testing

    request = PaymentRequest(
        amount=amount,
        currency="USD",
        destination=settings.xrpl_destination_address,
        idempotency_key=f"smoke-single-{os.urandom(4).hex()}",
        memo="Vouch smoke test",
    )

    print(f"\nSending {amount} to {settings.xrpl_destination_address}...")
    print(f"IOU mode: {xrpl_adapter._uses_iou()}")
    print(f"Network: {xrpl_adapter.network}")

    receipt = xrpl_adapter.send(request)

    print(f"TX ID: {receipt.tx_id}")
    print(f"Status: {receipt.status}")
    print(f"Explorer: {receipt.explorer_url}")
    print(f"Currency: {receipt.currency}")
    print(f"Raw: {receipt.raw}")

    assert receipt.status == PaymentStatus.SETTLED
    assert receipt.tx_id
    assert receipt.explorer_url
    assert receipt.explorer_url.startswith("https://testnet.xrpl.org/transactions/")

    status = xrpl_adapter.get_status(receipt.tx_id)
    assert status == PaymentStatus.SETTLED


def test_xrpl_live_batch_payment(xrpl_adapter):
    """Send a batch of payments on the XRPL testnet (tests Batch tx or fallback)."""
    settings = get_settlement_settings()

    requests = [
        PaymentRequest(
            amount=Decimal("0.01"),
            currency="USD",
            destination=settings.xrpl_destination_address,
            idempotency_key=f"smoke-batch-{i}-{os.urandom(4).hex()}",
            memo=f"Vouch batch smoke test {i}",
            metadata={"destination_tag": 1000 + i},
        )
        for i in range(2)
    ]

    print(f"\nSending batch of {len(requests)} payments...")
    print(f"IOU mode: {xrpl_adapter._uses_iou()}")
    print(f"Batch supported: {xrpl_adapter._batch_supported()}")

    receipts = xrpl_adapter.send_batch(requests, atomic=True)

    for i, receipt in enumerate(receipts):
        print(f"\nPayment {i}:")
        print(f"  TX ID: {receipt.tx_id}")
        print(f"  Status: {receipt.status}")
        print(f"  Explorer: {receipt.explorer_url}")
        print(f"  Batch mode: {receipt.raw.get('batch_mode', 'N/A')}")
        if receipt.raw.get("batch_hash"):
            print(f"  Batch TX: {receipt.raw['batch_hash']}")

        assert receipt.status == PaymentStatus.SETTLED
        assert receipt.tx_id
        assert receipt.explorer_url

    batch_mode = receipts[0].raw.get("batch_mode")
    if batch_mode == "sequential":
        print("\nNote: Batch amendment not available on testnet, used sequential fallback")
    elif batch_mode in ("atomic", "independent"):
        print(f"\nUsed XRPL Batch transaction ({batch_mode} mode)")


def test_xrpl_idempotency(xrpl_adapter):
    """Verify idempotency: same key should return same receipt without double-paying."""
    settings = get_settlement_settings()
    idem_key = f"smoke-idem-{os.urandom(4).hex()}"

    request = PaymentRequest(
        amount=Decimal("0.01"),
        currency="USD",
        destination=settings.xrpl_destination_address,
        idempotency_key=idem_key,
        memo="Idempotency test",
    )

    print(f"\nFirst send with key {idem_key}...")
    first = xrpl_adapter.send(request)
    print(f"TX ID: {first.tx_id}")

    print("Second send with same key (should return cached receipt)...")
    second = xrpl_adapter.send(request)
    print(f"TX ID: {second.tx_id}")

    assert first.tx_id == second.tx_id, "Idempotency failed: different tx_id on retry"
    print("Idempotency verified: same tx_id returned")
