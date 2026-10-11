"""The orchestrator timeline (``steps`` on the payment payload): the steps the graph ran for one card, in
order, each naming the tool or model, whether it was code / LLM / model / human, its per-card duration,
status and a one-line result; the classifier engine is reported as recorded (deterministic unless the
Decider or the chat classifier was actually asked and accepted)."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from vouch import main
from vouch.audit import AuditStore
from vouch.decider import FORMATS, TOOLS, FakeDeciderClient, choice_answer
from vouch.demo.samples import make_pdf
from vouch.service import VouchService
from vouch.steps import steps_of

STEP_KEYS = {
    "id",
    "seq",
    "label",
    "tool",
    "kind",
    "node",
    "duration_ms",
    "duration_scope",
    "status",
    "summary",
    "detail",
    "at",
}
KINDS = {"deterministic", "llm", "model", "human"}
STATUSES = {"ok", "flagged", "hold", "denied", "pending", "skipped", "failed"}
GRAPH_ORDER = [
    "intake",
    "format",
    "read",
    "screen",
    "check",
    "score",
    "investigate",
    "policy",
    "writer",
    "approval",
    "settlement",
]

INVOICE_LINES = [
    "From: Prairie Packaging Supply",
    "Invoice No: PPS-5001",
    "Invoice Date: 2026-10-07",
    "Total Due: $1,180.00",
    "Due Date: 2026-10-30",
    "IBAN: US021000089912",
]


@pytest.fixture
def svc(settings, tmp_path) -> VouchService:
    settings = settings.model_copy(update={"data_dir": tmp_path, "seed_demo": False})
    service = VouchService(settings, store=AuditStore("sqlite://"), seed_demo=False, restore=False)
    service.seed(run_demo=True, background_vendors=40)
    main.set_service(service)
    try:
        yield service
    finally:
        main.set_service(None)


def _by_vendor(payments: list[dict], prefix: str) -> dict:
    return next(p for p in payments if p["vendor"]["name"].startswith(prefix))


def _step(payment: dict, step_id: str) -> dict:
    return next(s for s in payment["steps"] if s["id"] == step_id)


def test_every_payment_carries_a_well_formed_ordered_timeline(svc):
    payments = svc.payments()
    assert payments
    for p in payments:
        steps = p["steps"]
        assert steps, p["id"]
        assert [s["seq"] for s in steps] == list(range(1, len(steps) + 1))
        assert len({s["id"] for s in steps}) == len(steps), "one entry per step"
        for s in steps:
            assert set(s) >= STEP_KEYS, STEP_KEYS - set(s)
            assert s["kind"] in KINDS and s["status"] in STATUSES
            assert s["tool"] and s["label"] and s["summary"]
            assert isinstance(s["detail"], list)
            if s["duration_ms"] is None:
                assert s["duration_scope"] is None
            else:
                assert s["duration_ms"] >= 0 and s["duration_scope"] in ("card", "run", "batch")
        # the graph order, intake first; format and read swap depending on when the route was decided
        ranks = [GRAPH_ORDER.index("read" if s["id"] == "format" else s["id"]) for s in steps]
        assert ranks[0] == 0 and ranks == sorted(ranks)
        # the deterministic steps report per-card timings measured by the engine
        for step_id in ("read", "screen", "check", "policy"):
            step = next((s for s in steps if s["id"] == step_id), None)
            if step is not None:
                assert step["kind"] == "deterministic" and step["duration_scope"] == "card", step_id


def test_demo_cards_show_the_real_tools_results_and_statuses(svc):
    payments = svc.payments()

    apex = _by_vendor(payments, "Apex")
    check = _step(apex, "check")
    assert check["status"] == "flagged" and "bank shared by 3 vendors" in check["summary"]
    assert any(line.startswith("ring: bank shared with 2 other vendor(s)") for line in check["detail"])
    score = _step(apex, "score")
    assert score["kind"] in ("model", "deterministic") and score["summary"].startswith("fake_vendor ")
    assert "legitimacy" in score["summary"] and score["duration_scope"] == "run"
    assert score["tool"].startswith(("VouchNet", "heuristic"))
    policy = _step(apex, "policy")
    assert policy["status"] == "hold" and policy["lane"] == "hold"
    assert policy["tool"].startswith("Cedar default-deny")
    assert "hold permitted for the system" in policy["summary"]
    assert "approve/settle denied for the agent" in policy["summary"] and policy["agent_denied"] is True
    assert _step(apex, "approval")["status"] == "hold" and _step(apex, "approval")["kind"] == "human"
    assert not any(s["id"] == "settlement" for s in apex["steps"]), "nothing settled while on hold"

    sonora = _by_vendor(payments, "Sonora")
    assert _step(sonora, "intake")["summary"].startswith("email received")
    sender_line = next(line for line in _step(sonora, "check")["detail"] if line.startswith("sender:"))
    assert "lookalike" in sender_line or "spf" in sender_line
    assert _step(sonora, "investigate")["summary"]
    writer = _step(sonora, "writer")
    assert writer["kind"] == "deterministic" and writer["source"] == "template"

    prairie = _by_vendor(payments, "Prairie")
    assert _step(prairie, "read")["summary"].startswith("$1,180.00 · Prairie Packaging Supply")
    assert _step(prairie, "screen")["status"] == "ok" and _step(prairie, "screen")["match"] == "known"
    assert _step(prairie, "check")["summary"].startswith("clean")
    assert _step(prairie, "approval")["summary"].startswith("fast-pay")
    settlement = _step(prairie, "settlement")
    assert settlement["status"] == "ok" and settlement["tx_id"] and settlement["tool"].startswith("mock")
    assert settlement["duration_scope"] == "batch"
    # structured JSON submissions carry nothing to route: no format step is invented
    assert not any(s["id"] == "format" for s in prairie["steps"])


def test_owner_actions_and_settlement_extend_the_timeline(svc):
    client = TestClient(main.app)
    rhein = _by_vendor(client.get("/v1/payments").json(), "Rheinland")
    assert _step(rhein, "approval")["status"] == "pending"
    approved = client.post(f"/v1/payments/{rhein['id']}/approve", json={"note": "ok", "author": "Dana"})
    assert approved.status_code == 200
    step = _step(approved.json(), "approval")
    assert step["status"] == "ok" and step["summary"] == "approved by Dana"
    assert any(line.startswith("approved by Dana") for line in step["detail"])
    assert _step(approved.json(), "settlement")["status"] == "pending"

    receipt = client.post("/v1/batch/settle", json={"payment_ids": [rhein["id"]], "funding": "now"}).json()
    settled = client.get(f"/v1/payments/{rhein['id']}").json()
    settlement = _step(settled, "settlement")
    assert settlement["status"] == "ok" and settlement["tx_id"] == receipt["tx_id"]
    assert settlement["kind"] == "deterministic" and settlement["duration_ms"] is not None
    assert settled["steps"][-1]["id"] == "settlement"


def test_classifier_engine_is_reported_as_recorded(settings, service_factory, tmp_path):
    """Policy ``auto``: an obvious PDF is routed by code and the step says so (0 model calls); the Decider
    only shows up, with its confidence and latency, when the route was ambiguous and it was asked."""
    fake = FakeDeciderClient(
        {
            "format": choice_answer("excel_attachment", 0.9, list(FORMATS)),
            "tool": choice_answer("excel_reader", 0.85, list(TOOLS)),
        },
        latency_ms=900.0,
    )
    engine = service_factory(decider=fake)
    s = settings.model_copy(update={"data_dir": tmp_path, "seed_demo": False})
    svc = VouchService(s, engine=engine, store=AuditStore("sqlite://"), seed_demo=False, restore=False)

    run = svc.intake_files([("inv.pdf", "application/pdf", make_pdf(INVOICE_LINES, "Invoice"))])
    card = run.card_list()[0]
    steps = steps_of(engine, run, card)
    ids = [s["id"] for s in steps]
    assert ids[:3] == ["intake", "format", "read"], "routed before extraction: format precedes read"
    fmt = steps[1]
    assert fmt["engine"] == "deterministic" and fmt["kind"] == "deterministic" and fmt["model_calls"] == 0
    assert fmt["confidence"] == 1.0 and "no model was asked" in fmt["summary"]
    assert fmt["tool"].startswith("deterministic route") and len(fake.calls) == 0
    assert steps[0]["summary"] == "upload received, 1 file" and steps[0]["files"] == ["inv.pdf"]
    read = steps[2]
    assert read["tool"].startswith("PDF text parser") and read["llm_calls"] == 0
    assert read["summary"].startswith("$1,180.00 · Prairie Packaging Supply · PPS-5001")

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    for line in INVOICE_LINES:
        ws.append(line.split(": ", 1))
    buf = io.BytesIO()
    wb.save(buf)
    run = svc.intake_files(
        [
            (
                "terms.pdf",
                "application/pdf",
                make_pdf(
                    ["General terms and conditions of sale", "Payment is due within thirty days."], "Terms"
                ),
            ),
            ("inv.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buf.getvalue()),
        ]
    )
    fmt = _step(svc.payment(run.card_list()[0].id), "format")
    assert fmt["engine"] == "decider" and fmt["kind"] == "model" and len(fake.calls) == 2
    assert fmt["tool"].startswith("Strands Decider 2B") and fmt["confidence"] == 0.9
    assert fmt["model_calls"] == 2 and fmt["duration_ms"] == 1800.0 and fmt["duration_scope"] == "card"
    assert "excel_attachment → excel_reader" in fmt["summary"] and "2 model calls" in fmt["summary"]
    assert any(line.startswith("deterministic route was") for line in fmt["detail"])
