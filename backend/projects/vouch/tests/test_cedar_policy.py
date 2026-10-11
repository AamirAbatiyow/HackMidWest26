"""Cedar authorization: default deny, the nine permits, and parity between the Cedar engine and the
Python mirror used when cedarpy is unavailable."""

from __future__ import annotations

import itertools

import pytest

from vouch.policy import PaymentAttrs, authorize
from vouch.policy.engine import _mirror, cedar_available, policy_ids

PRINCIPALS = ("Owner", "System", "Model", "Vendor")
ACTIONS = (
    "approve",
    "hold",
    "appeal",
    "settle",
    "fast_pay",
    "change_bank_details",
    "read",
    "explain",
    "deny_vendor",
    "modify_amount",
    "add_fee",
    "round_amount",
    "approve_kickback",
    "decline_kickback",
    "send_kickback",
    "delete",
)
LIFECYCLES = ("pending", "approved", "held", "appealed", "settled")
KICKBACK_APPROVED = {"kickback_approved": True, "kickback_sent": False}


def _attrs(lifecycle="pending", **kw) -> PaymentAttrs:
    base = {
        "status": "vouched",
        "lifecycle": lifecycle,
        "risk": "none",
        "trust_score": 95,
        "fast_pay_eligible": True,
        "bank_changed": False,
        "bank_change_verified": False,
        "amount_cents": 100_000,
        "vendor_known": True,
    }
    base.update(kw)
    return PaymentAttrs(**base)


def test_policy_file_declares_nine_permits():
    ids = policy_ids()
    assert ids[:9] == ["P-01", "P-02", "P-03", "P-04", "P-05", "P-06", "P-07", "P-08", "P-09"]


def test_default_deny_for_unknown_actions_and_principals():
    for principal in PRINCIPALS:
        out = authorize(principal, "delete", _attrs())
        assert not out.allowed and out.reasons == ["DEFAULT-DENY"]
    assert not authorize("Vendor", "approve", _attrs()).allowed


def test_owner_permits():
    assert authorize("Owner", "approve", _attrs("pending")).reasons == ["P-01"]
    assert authorize("Owner", "approve", _attrs("held")).reasons == ["P-01"]
    assert authorize("Owner", "approve", _attrs("appealed")).reasons == ["P-01"]
    assert not authorize("Owner", "approve", _attrs("settled")).allowed
    assert not authorize("Owner", "approve", _attrs("approved")).allowed
    assert authorize("Owner", "hold", _attrs("approved")).reasons == ["P-02"]
    assert not authorize("Owner", "hold", _attrs("settled")).allowed
    assert authorize("Owner", "settle", _attrs("approved"), {"owner_approval_recorded": True}).reasons == [
        "P-05"
    ]
    assert not authorize("Owner", "settle", _attrs("approved")).allowed, (
        "no settle without a recorded approval"
    )
    assert not authorize("Owner", "settle", _attrs("pending"), {"owner_approval_recorded": True}).allowed
    assert authorize("Owner", "change_bank_details", _attrs(), {"callback_verified": True}).reasons == [
        "P-06"
    ]
    assert not authorize("Owner", "change_bank_details", _attrs()).allowed


def test_only_the_owner_may_decide_a_kickback_email_and_only_before_settlement():
    for lifecycle in ("pending", "approved", "held", "appealed"):
        assert authorize("Owner", "approve_kickback", _attrs(lifecycle)).reasons == ["P-08"], lifecycle
        assert authorize("Owner", "decline_kickback", _attrs(lifecycle)).reasons == ["P-08"], lifecycle
    assert not authorize("Owner", "approve_kickback", _attrs("settled")).allowed
    assert not authorize("Owner", "decline_kickback", _attrs("settled")).allowed
    for principal in ("System", "Model", "Vendor"):
        for action in ("approve_kickback", "decline_kickback"):
            out = authorize(principal, action, _attrs(), {"owner_approval_recorded": True})
            assert not out.allowed and out.reasons == ["DEFAULT-DENY"], (principal, action)


def test_sending_a_kickback_needs_the_owners_approval_on_record_and_happens_once():
    """P-09: the approved draft leaves through the owner, once, before settlement. Approving (P-08) grants
    nothing by itself, a sent draft cannot be sent again, and no other principal has a permit whatever
    the context claims - so nothing in the automated system can email a vendor."""
    for lifecycle in ("pending", "approved", "held", "appealed"):
        assert authorize("Owner", "send_kickback", _attrs(lifecycle), KICKBACK_APPROVED).reasons == ["P-09"]
    assert not authorize("Owner", "send_kickback", _attrs("settled"), KICKBACK_APPROVED).allowed
    assert not authorize("Owner", "send_kickback", _attrs()).allowed, "awaiting the owner: no send"
    assert not authorize("Owner", "send_kickback", _attrs(), {"kickback_approved": False}).allowed
    already_sent = {"kickback_approved": True, "kickback_sent": True}
    out = authorize("Owner", "send_kickback", _attrs(), already_sent)
    assert not out.allowed and out.reasons == ["DEFAULT-DENY"], "a draft is sent at most once"
    assert not authorize("Owner", "send_kickback", _attrs(), {"kickback_sent": True}).allowed
    forged = {**KICKBACK_APPROVED, "owner_approval_recorded": True, "approval_limit_cents": 10**9}
    for principal in ("System", "Model", "Vendor"):
        for ctx in ({}, KICKBACK_APPROVED, forged):
            out = authorize(principal, "send_kickback", _attrs(), ctx)
            assert not out.allowed and out.reasons == ["DEFAULT-DENY"], (principal, ctx)


def test_system_may_hold_and_fast_pay_but_never_deny_or_edit():
    assert authorize("System", "hold", _attrs()).reasons == ["P-03"]
    ok = authorize("System", "fast_pay", _attrs(amount_cents=200_000), {"approval_limit_cents": 250_000})
    assert ok.reasons == ["P-04"]
    over = authorize("System", "fast_pay", _attrs(amount_cents=300_000), {"approval_limit_cents": 250_000})
    assert not over.allowed
    unverified_bank = authorize(
        "System", "fast_pay", _attrs(bank_changed=True), {"approval_limit_cents": 250_000}
    )
    assert not unverified_bank.allowed
    verified_bank = authorize(
        "System",
        "fast_pay",
        _attrs(bank_changed=True, bank_change_verified=True),
        {"approval_limit_cents": 250_000},
    )
    assert verified_bank.allowed
    for action in ("deny_vendor", "modify_amount", "add_fee", "round_amount", "approve"):
        assert not authorize("System", action, _attrs()).allowed, action


def test_model_principal_has_no_permits_at_all():
    """The model's output is advice: no policy grants `Model` anything, not even read."""
    for action in ACTIONS:
        ctx = {"owner_approval_recorded": True, **KICKBACK_APPROVED}
        out = authorize("Model", action, _attrs("approved"), ctx)
        assert not out.allowed and out.reasons == ["DEFAULT-DENY"], action
    assert authorize("System", "explain", _attrs()).reasons == ["P-07"]


@pytest.mark.skipif(not cedar_available(), reason="cedarpy not installed; parity needs both engines")
def test_cedar_and_python_mirror_agree_on_the_full_matrix():
    cold = {"approval_limit_cents": 0, "owner_approval_recorded": False, "callback_verified": False}
    warm = {"approval_limit_cents": 250_000, "owner_approval_recorded": True, "callback_verified": True}
    contexts = [
        {**cold, "kickback_approved": False, "kickback_sent": False},
        {**warm, "kickback_approved": False, "kickback_sent": False},
        {**warm, "kickback_approved": True, "kickback_sent": False},
        {**warm, "kickback_approved": True, "kickback_sent": True},
    ]
    attr_variants = [
        _attrs(lc, **extra)
        for lc in LIFECYCLES
        for extra in (
            {},
            {"bank_changed": True},
            {"bank_changed": True, "bank_change_verified": True},
            {"status": "verify", "fast_pay_eligible": False, "vendor_known": False},
        )
    ]
    mismatches = []
    for principal, action, attrs, ctx in itertools.product(PRINCIPALS, ACTIONS, attr_variants, contexts):
        cedar = authorize(principal, action, attrs, ctx)
        mirror = _mirror(principal, action, attrs, ctx)
        assert cedar.engine == "cedar"
        if (cedar.allowed, cedar.reasons) != (mirror.allowed, mirror.reasons):
            mismatches.append((principal, action, attrs.lifecycle, ctx, cedar, mirror))
    assert not mismatches, mismatches[:5]
