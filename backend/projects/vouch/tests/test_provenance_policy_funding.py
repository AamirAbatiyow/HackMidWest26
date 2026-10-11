from dataclasses import asdict
from datetime import date, timedelta

from vouch.cards import PaymentCard
from vouch.domain import Invoice, Lane, ModelScores, PastPayment, Resolution, Vendor
from vouch.funding import CashForecast, recommend
from vouch.kernel import Limits, check_invoice
from vouch.policy import (
    R_BANK,
    R_HIGH_RISK,
    R_LIMIT,
    R_LLM_AMOUNT,
    build_policy,
    evaluate_batch,
    evaluate_card,
)
from vouch.provenance import check_provenance, extract_numbers

TODAY = date(2026, 10, 10)
FACTS = ["$9,850.00", "2026-10-11", "****5678", "+52-662-555-0199", "87%", "SFP-88213", "1.0x"]


def test_provenance_accepts_facts_in_any_format():
    text = (
        "Sonora's invoice SFP-88213 for $9,850 is due Oct 11, 2026; risk 87%. Amount is 1.0x usual. 3 flags."
    )
    assert check_provenance(text, FACTS).ok


def test_provenance_rejects_invented_numbers():
    report = check_provenance("Pay $9,900.00 by 2026-10-12 to account 99887766 (risk 12%).", FACTS)
    assert not report.ok
    assert {"money:9900", "date:2026-10-12", "num:99887766", "pct:12"} <= set(report.unknown)


def test_extract_numbers_normalizes():
    assert ("money", "1234.5") in extract_numbers("$1,234.50")
    assert ("date", "2026-10-11") in extract_numbers("10/11/2026")


def _card(vendor: Vendor, inv: Invoice, risk: float = 0.01, legit: float = 0.95) -> PaymentCard:
    ch = check_invoice(inv, vendor, [inv], Limits(), TODAY)
    scores = ModelScores(
        risk={"ato_bec": risk, "insider": 0.01, "fake_vendor": 0.01},
        anomaly=0.1,
        legitimacy=legit,
        top_class="ato_bec",
        model_version="t",
        scorer="t",
    )
    return PaymentCard(
        id=inv.id,
        run_id="r",
        invoice=inv,
        vendor=vendor,
        payable_cents=inv.amount_cents,
        checks=asdict(ch),
        flags=ch.flags(),
        scores=scores,
    )


def _vendor(**kw) -> Vendor:
    base = dict(
        id="v1",
        name="Acme",
        country="US",
        email="a@acme.com",
        phone="+1-816-555-0100",
        address="1 Main St",
        tax_id="12-3456789",
        bank_account="US1234567890",
        bank_country="US",
        created_days_ago=900,
        oob_verified=True,
        history=[PastPayment(amount_cents=95_000 + i * 1_317, days_ago=30 + i) for i in range(5)],
    )
    return Vendor(**{**base, **kw})


def _inv(amount=100_000, **kw) -> Invoice:
    base = dict(
        id="i1",
        vendor_id="v1",
        vendor_name="Acme",
        invoice_number="INV-1",
        amount_cents=amount,
        issue_date=TODAY,
        due_date=TODAY + timedelta(days=20),
        po_number="PO-1",
        delivery_confirmed=True,
        bank_account="US1234567890",
    )
    return Invoice(**{**base, **kw})


POLICY = build_policy(Limits())


def test_lanes_fast_pay_standard_hold():
    assert evaluate_card(POLICY, _card(_vendor(), _inv(100_000))).lane == Lane.FAST_PAY
    assert evaluate_card(POLICY, _card(_vendor(), _inv(400_000))).lane == Lane.STANDARD
    held = evaluate_card(POLICY, _card(_vendor(), _inv(100_000), risk=0.95, legit=0.1))
    assert held.lane == Lane.HOLD and R_HIGH_RISK in held.reasons and held.required_actions


def test_high_risk_with_high_legitimacy_is_not_held():
    """Honest small vendors are protected: model risk alone needs low legitimacy to hold."""
    assert evaluate_card(POLICY, _card(_vendor(), _inv(400_000), risk=0.8, legit=0.9)).lane == Lane.STANDARD


def test_bank_change_needs_out_of_band_confirmation():
    v = _vendor(bank_changed_days_ago=5, bank_change_confirmed_oob=False)
    card = _card(v, _inv(400_000))
    assert R_BANK in evaluate_card(POLICY, card).reasons
    card.resolutions.append(Resolution(kind="confirm_bank", actor="owner"))
    assert evaluate_card(POLICY, card).lane == Lane.STANDARD
    confirmed = _card(_vendor(bank_changed_days_ago=5, bank_change_confirmed_oob=True), _inv(100_000))
    assert evaluate_card(POLICY, confirmed).lane == Lane.STANDARD  # never fast-pay right after a bank change


def test_llm_originated_amount_can_never_be_resolved_away():
    card = _card(_vendor(), _inv(100_000, amount_origin="llm"))
    card.resolutions += [
        Resolution(kind="resolve_risk", actor="owner", note="looks fine"),
        Resolution(kind="limit_override", actor="owner"),
    ]
    out = evaluate_card(POLICY, card)
    assert out.lane == Lane.HOLD and R_LLM_AMOUNT in out.reasons
    assert not evaluate_batch(POLICY, [card], owner_approved=True).allowed


def test_limits_single_and_batch():
    big = _card(_vendor(), _inv(6_000_000))
    assert R_LIMIT in evaluate_card(POLICY, big).reasons
    big.resolutions.append(Resolution(kind="limit_override", actor="owner", note="annual contract"))
    assert evaluate_card(POLICY, big).allowed
    tight = build_policy(Limits(batch_limit_cents=50_000))
    assert not evaluate_batch(tight, [_card(_vendor(), _inv(100_000))], owner_approved=True).allowed
    assert not evaluate_batch(POLICY, [_card(_vendor(), _inv(400_000))], owner_approved=False).allowed


def test_owner_hold_and_release():
    card = _card(_vendor(), _inv(400_000))
    card.resolutions.append(Resolution(kind="owner_hold", actor="owner"))
    assert evaluate_card(POLICY, card).lane == Lane.HOLD
    card.resolutions.append(Resolution(kind="release_hold", actor="owner"))
    assert evaluate_card(POLICY, card).lane == Lane.STANDARD


def test_funding_discount_schedule_and_never_late():
    fast = _card(_vendor(), _inv(100_000))
    disc = _card(_vendor(id="v2"), _inv(400_000, id="i2", vendor_id="v2", discount_bps=200, discount_days=10))
    later = _card(
        _vendor(id="v3"), _inv(400_000, id="i3", vendor_id="v3", due_date=TODAY + timedelta(days=20))
    )
    for c in (fast, disc, later):
        c.policy = evaluate_card(POLICY, c)
    recs = recommend([fast, disc, later], CashForecast(), TODAY)
    assert recs["i1"]["action"] == "pay_now"
    assert recs["i2"]["action"] == "pay_now" and recs["i2"]["discount_cents"] == 8_000
    assert (
        recs["i3"]["action"] == "schedule"
        and recs["i3"]["pay_on"] == (TODAY + timedelta(days=19)).isoformat()
    )
    assert all(r["on_time"] for r in recs.values())
    poor = recommend(
        [later],
        CashForecast(opening_balance_cents=100_000, receivables=[(30, 9_000_000)], committed=[]),
        TODAY,
    )
    assert poor["i3"]["shortfall"] is True
