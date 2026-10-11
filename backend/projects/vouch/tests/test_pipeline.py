"""End-to-end through the Strands graph with a stubbed (scripted) LLM and the mock ledger."""

from datetime import date

import pytest

from vouch.demo import demo_submissions
from vouch.domain import CardStatus, Lane
from vouch.llm import LLMRuntime
from vouch.pipeline import approve, execute
from vouch.policy import R_BANK, R_DUPLICATE, R_INJECTION, R_RING

TODAY = date(2026, 10, 10)


def _by_vendor(run):
    return {c.invoice.vendor_name.split()[0]: c for c in run.card_list()}


def _scripted_happy() -> LLMRuntime:
    """Intake quotes the real total; explainer only uses facts; investigators recommend a call-back."""
    return LLMRuntime.scripted(
        {
            "intake": [
                {
                    "tool": "IntakeExtraction",
                    "input": {
                        "vendor_name": "Bao Lin Ceramics",
                        "invoice_number": "BLC-0042",
                        "amount_quote": "USD 640.00",
                        "due_date_quote": "2026-10-22",
                        "suspicious_instructions": [],
                    },
                }
            ],
            "investigator:ato_bec": [
                {
                    "tool": "InvestigationReport",
                    "input": {
                        "summary": "Bank details on the invoice (****5678) differ from the account on file.",
                        "vendor_questions": [
                            "Call +52-662-555-0199 and ask whether the bank account changed."
                        ],
                        "recommended_action": "verify_bank_by_callback",
                    },
                }
            ],
            "explainer": [
                {
                    "tool": "Explanations",
                    "input": {
                        "items": [
                            {"card_id": "*", "text": "Decision is based on the kernel facts for this card."}
                        ]
                    },
                }
            ],
        }
    )


def test_happy_path_fast_pay_then_owner_approval(service_factory):
    svc = service_factory(llm=_scripted_happy())
    run = execute(svc, svc.new_run(demo_submissions(TODAY)))
    cards = _by_vendor(run)

    assert cards["Prairie"].policy.lane == Lane.FAST_PAY and cards["Prairie"].status == CardStatus.PAID
    assert cards["Prairie"].receipt["tx_id"].startswith("mock_")
    assert cards["Rheinland"].policy.lane == Lane.STANDARD
    assert (
        cards["Rheinland"].funding["action"] == "pay_now"
        and cards["Rheinland"].funding["discount_cents"] == 16_480
    )
    bao = cards["Bao"]
    assert bao.policy.lane == Lane.STANDARD, bao.policy.reasons  # new small vendor is not blocked
    assert bao.funding["on_time"] and bao.invoice.amount_cents == 64_000

    # Paused at the Strands interrupt before `settle`.
    assert run.status == "awaiting_approval" and run.pending["name"] == "owner_approval"
    assert {c["vendor"] for c in run.pending["reason"]["cards"]} == {
        "Rheinland Gewürze GmbH",
        "Bao Lin Ceramics",
    }
    assert svc.llm.stats.calls >= 3  # intake + investigators + explainer
    assert all(c.explanation for c in run.card_list())

    approve(svc, run, {"approved": True, "approver": "dana"})
    assert run.status == "completed"
    assert cards["Rheinland"].status == CardStatus.PAID and cards["Bao"].status == CardStatus.PAID
    assert len(run.settlements) == 2 and run.settlements[-1]["total_cents"] == 824_000 + 64_000


def test_attack_path_every_bad_actor_is_held_with_a_way_forward(service_factory):
    svc = service_factory(llm=_scripted_happy())
    run = execute(svc, svc.new_run(demo_submissions(TODAY)))
    cards = _by_vendor(run)
    sonora, midwest, apex = cards["Sonora"], cards["Midwest"], cards["Apex"]
    assert R_BANK in sonora.policy.reasons and R_INJECTION in sonora.policy.reasons
    assert R_DUPLICATE in midwest.policy.reasons
    assert R_RING in apex.policy.reasons
    for c in (sonora, midwest, apex):
        assert c.status == CardStatus.HOLD and c.policy.required_actions and c.receipt is None
        assert c.investigation is not None
    assert sonora.investigation.source == "llm" and sonora.investigation.provenance_ok

    approve(svc, run, {"approved": True})
    assert all(c.status == CardStatus.HOLD for c in (sonora, midwest, apex))


def test_holds_resolve_then_settle_through_a_new_approval(service_factory):
    svc = service_factory()
    run = execute(svc, svc.new_run(demo_submissions(TODAY)))
    approve(svc, run, {"approved": True})
    midwest = _by_vendor(run)["Midwest"]
    from vouch.domain import Resolution

    svc.resolve(
        midwest.id, Resolution(kind="appeal", actor="midwest-ar", note="INV-2291A is the October service")
    )
    assert midwest.status == CardStatus.HOLD  # an appeal is recorded but does not release money
    svc.resolve(
        midwest.id, Resolution(kind="resolve_risk", actor="dana", note="Checked: separate October work order")
    )
    assert midwest.status == CardStatus.READY

    approve(svc, run, {"approved": True, "card_ids": [midwest.id]})
    assert midwest.status == CardStatus.PAID


def test_decline_moves_no_money(service_factory):
    svc = service_factory()
    run = execute(svc, svc.new_run(demo_submissions(TODAY)))
    paid_before = [c.id for c in run.card_list() if c.status == CardStatus.PAID]
    approve(svc, run, False)
    assert [c.id for c in run.card_list() if c.status == CardStatus.PAID] == paid_before
    assert run.status == "completed"


def test_offline_mode_uses_templates_and_no_llm(service):
    run = execute(service, service.new_run(demo_submissions(TODAY)))
    assert service.llm.stats.calls == 0
    assert all(c.explanation_source == "template" for c in run.card_list())
    assert run.node_ms.keys() >= {
        "intake",
        "kernel",
        "score",
        "investigate",
        "policy",
        "funding",
        "explain",
        "fast_pay",
    }


@pytest.mark.parametrize("bad", ["yes please", {"approved": "true"}, None, 1])
def test_ambiguous_approvals_are_declines(service_factory, bad):
    svc = service_factory()
    run = execute(svc, svc.new_run(demo_submissions(TODAY)[1:2]))
    approve(svc, run, bad)
    assert run.card_list()[0].status == CardStatus.READY
