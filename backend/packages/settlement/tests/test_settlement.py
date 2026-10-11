from decimal import Decimal

import pytest

from hm_core.errors import ConfigError
from hm_settlement import (
    MockSettlementAdapter,
    PaymentRequest,
    PaymentStatus,
    SettlementSettings,
    make_adapter,
)
from hm_settlement.arc_adapter import ArcUSDCAdapter
from hm_settlement.xrpl_adapter import XRPLTestnetAdapter


def req(key="k1", amount="12.50"):
    return PaymentRequest(amount=Decimal(amount), destination="rDEST", idempotency_key=key)


def test_mock_send_is_idempotent():
    adapter = MockSettlementAdapter()
    first = adapter.send(req())
    again = adapter.send(req())
    assert first.tx_id == again.tx_id
    assert adapter.get_status(first.tx_id) == PaymentStatus.SETTLED
    assert adapter.verify(first)


def test_mock_hold_release_cancel():
    adapter = MockSettlementAdapter()
    held = adapter.hold(req("milestone-1"))
    assert held.status == PaymentStatus.HELD
    assert adapter.release(held.tx_id).status == PaymentStatus.SETTLED
    other = adapter.hold(req("milestone-2"))
    assert adapter.cancel(other.tx_id).status == PaymentStatus.CANCELLED
    with pytest.raises(ValueError):
        adapter.release(other.tx_id)


def test_amount_must_be_positive():
    with pytest.raises(ValueError):
        req(amount="0")


def test_factory_and_stubs():
    assert isinstance(make_adapter("mock"), MockSettlementAdapter)
    assert isinstance(make_adapter("arc"), ArcUSDCAdapter)
    with pytest.raises(ValueError):
        make_adapter("paypal")


def test_mock_send_batch_defaults_to_sequential_and_idempotent():
    adapter = MockSettlementAdapter()
    receipts = adapter.send_batch([req("a"), req("b"), req("a")])
    assert receipts[0].tx_id == receipts[2].tx_id != receipts[1].tx_id


def _xrpl(**settings):
    pytest.importorskip("xrpl")
    from xrpl.wallet import Wallet

    s = SettlementSettings(xrpl_destination_address="rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe", **settings)
    return XRPLTestnetAdapter(settings=s, client=object(), wallet=Wallet.create())


def test_xrpl_requires_a_seed():
    pytest.importorskip("xrpl")
    with pytest.raises(ConfigError):
        XRPLTestnetAdapter(settings=SettlementSettings(xrpl_wallet_seed=""))


def test_xrpl_scaling_destination_and_memo():
    adapter = _xrpl(xrpl_xrp_per_usd=Decimal("0.0001"))
    r = PaymentRequest(
        amount=Decimal("8240.00"),
        destination="vendor:v-rheinland",
        idempotency_key="vouch:k",
        memo="RG-1",
        metadata={"destination_tag": 1002},
    )
    assert adapter.to_drops(r) == "824000"  # $8,240 -> 0.824 test XRP
    tx = adapter._payment(r)
    assert tx.destination == "rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe" and tx.destination_tag == 1002
    assert bytes.fromhex(tx.memos[0].memo_data).decode().startswith("vouch:k|RG-1")
    assert adapter.explorer_url("ABC") == "https://testnet.xrpl.org/transactions/ABC"


def test_xrpl_batch_is_idempotent_per_key(monkeypatch):
    adapter = _xrpl()
    calls = []

    def fake_batch(chunk, atomic):
        calls.append([r.idempotency_key for r in chunk])
        return [adapter._receipt(r, f"H{i}", True, {"batch_hash": "B"}) for i, r in enumerate(chunk)]

    monkeypatch.setattr(adapter, "_submit_batch", fake_batch)
    first = adapter.send_batch([req("a"), req("b")])
    again = adapter.send_batch([req("a"), req("b")])
    assert calls == [["a", "b"]] and [r.tx_id for r in first] == [r.tx_id for r in again]
