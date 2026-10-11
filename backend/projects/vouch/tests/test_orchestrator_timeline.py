"""Orchestrator timeline: ordered steps per card built from real run events, naming the tool or engine that
actually ran, with measured node durations, a status and a one-line result."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vouch import main
from vouch.audit import AuditStore
from vouch.demo.samples import make_csv
from vouch.orchestration import NODE_TIMED, STATUS_FLAG, STATUS_HOLD, STATUS_OK, card_timeline, run_timeline
from vouch.service import VouchService

STEP_KEYS = {
    "order",
    "step",
    "node",
    "tool",
    "engine",
    "duration_ms",
    "duration_scope",
    "status",
    "result",
    "detail",
}
PIPELINE = [
    "intake",
    "vendor screen",
    "bank check",
    "duplicate check",
    "ring check",
    "amount check",
    "score",
    "policy",
]


@pytest.fixture
def client(settings, tmp_path):
    settings = settings.model_copy(update={"data_dir": tmp_path, "seed_demo": False})
    service = VouchService(settings, store=AuditStore("sqlite://"), seed_demo=False, restore=False)
    service.seed(run_demo=True, background_vendors=40)
    main.set_service(service)
    try:
        yield TestClient(main.app)
    finally:
        main.set_service(None)


def _payment(client: TestClient, prefix: str) -> dict:
    return next(p for p in client.get("/v1/payments").json() if p["vendor"]["name"].startswith(prefix))


def _steps(timeline: dict) -> dict[str, dict]:
    return {s["step"]: s for s in timeline["steps"]}


def _positions(timeline: dict, names: list[str]) -> list[int]:
    order = [s["step"] for s in timeline["steps"]]
    return [order.index(n) for n in names]


def test_timeline_steps_are_ordered_and_timed_from_run_events(client):
    prairie = _payment(client, "Prairie")
    res = client.get(f"/v1/cards/{prairie['id']}/timeline")
    assert res.status_code == 200, res.text
    tl = res.json()
    assert tl["card_id"] == prairie["id"] and tl["run_id"] and tl["complete"] is True
    assert [s["order"] for s in tl["steps"]] == list(range(1, len(tl["steps"]) + 1))
    for s in tl["steps"]:
        assert set(s) >= STEP_KEYS, STEP_KEYS - set(s)
        assert s["status"] in ("ok", "flag", "hold", "pending")
        assert s["result"] and "\n" not in s["result"], "one-line result"
    positions = _positions(tl, PIPELINE)
    assert positions == sorted(positions), "steps follow the graph order intake -> ... -> policy"

    steps = _steps(tl)
    node_ms = {
        e["node"]: e["ms"]
        for e in client.get(f"/v1/runs/{tl['run_id']}/events").json()["events"]
        if e["type"] == "node_done"
    }
    assert (
        steps["bank check"]["duration_ms"] == node_ms["kernel"]
        and steps["bank check"]["duration_scope"] == "node"
    )
    assert steps["score"]["duration_ms"] == node_ms["score"]
    assert (
        steps["score"]["tool"].startswith("heuristic scorer")
        and steps["score"]["engine"] == "heuristic-fallback"
    )
    assert "92%" in steps["score"]["result"] or "legitimacy" in steps["score"]["result"]
    assert steps["policy"]["result"].startswith("lane: fast pay") and steps["policy"]["status"] == STATUS_OK
    assert steps["settlement"]["engine"] == "mock" and steps["settlement"]["result"].startswith(
        "settled $1,180.00"
    )
    assert steps["owner approval"]["result"].startswith("not required · fast-pay")
    assert steps["explain"]["tool"].startswith("template explanation"), (
        "offline LLM: no model call is claimed"
    )


def test_flags_and_holds_report_the_real_findings(client):
    sonora = _payment(client, "Sonora")
    steps = _steps(client.get(f"/v1/payments/{sonora['id']}/timeline").json())
    assert steps["sender check"]["status"] == STATUS_FLAG and "flag(s)" in steps["sender check"]["result"]
    assert steps["bank check"]["status"] == STATUS_FLAG
    assert "differs from the master file" in steps["bank check"]["result"]
    assert steps["policy"]["status"] == STATUS_HOLD and steps["policy"]["result"].startswith("lane: hold")
    assert (
        steps["owner approval"]["status"] == STATUS_HOLD
        and "on hold, not denied" in steps["owner approval"]["result"]
    )
    assert steps["investigate"]["tool"].startswith("template investigator [ato_bec]")

    midwest = _payment(client, "Midwest")
    steps = _steps(client.get(f"/v1/payments/{midwest['id']}/timeline").json())
    assert steps["duplicate check"]["status"] == STATUS_FLAG
    assert "possible duplicate of paid invoice INV-2291" in steps["duplicate check"]["result"]

    apex = _payment(client, "Apex")
    steps = _steps(client.get(f"/v1/payments/{apex['id']}/timeline").json())
    assert steps["ring check"]["status"] == STATUS_FLAG
    assert "bank shared with 2 other vendor(s)" in steps["ring check"]["result"]
    assert steps["ring check"]["detail"]["shared_attributes"]["bank"]


def test_intake_classification_names_the_engine_that_actually_decided(client):
    """Deterministic routing is reported as such, never as the Decider."""
    csv_bytes = make_csv(
        [
            ["From", "Bao Lin Ceramics"],
            ["Invoice No", "BLC-0101"],
            ["Invoice Date", "2026-10-09"],
            ["Total Due", "$640.00"],
            ["Due Date", "2026-10-30"],
            ["Bank account", "VN123456789012"],
        ]
    )
    res = client.post("/v1/intake/upload", files={"files": ("blc.csv", csv_bytes, "text/csv")})
    assert res.status_code == 200, res.text
    card = res.json()["payments"][0]
    tl = client.get(f"/v1/cards/{card['id']}/timeline").json()
    steps = _steps(tl)
    fmt = steps["format decision"]
    assert fmt["engine"] == "deterministic" and fmt["tool"] == "deterministic route"
    assert fmt["result"].startswith("deterministic route: csv_attachment → CSV parser · 0 model calls")
    assert "Decider" not in fmt["result"]
    assert fmt["detail"]["decider_calls"] == 0 and fmt["detail"]["llm_calls"] == 0
    read = steps["read/parse"]
    assert (
        read["tool"] == "CSV parser" and "amount $640.00" in read["result"] and "BLC-0101" in read["result"]
    )
    assert read["detail"]["documents"][0]["extractor"] == "csv"
    assert _positions(tl, ["intake", "format decision", "read/parse", "vendor screen"]) == sorted(
        _positions(tl, ["intake", "format decision", "read/parse", "vendor screen"])
    )


def test_owner_approval_and_cedar_authorization_appear_after_the_pipeline(client):
    rheinland = _payment(client, "Rheinland")
    before = _steps(client.get(f"/v1/cards/{rheinland['id']}/timeline").json())
    assert before["owner approval"]["status"] == "pending"

    res = client.post(f"/v1/payments/{rheinland['id']}/approve", json={"note": "ok", "author": "Dana"})
    assert res.status_code == 200, res.text
    tl = client.get(f"/v1/cards/{rheinland['id']}/timeline").json()
    names = [s["step"] for s in tl["steps"]]
    assert names.index("policy") < names.index("authorization") < names.index("owner approval")
    authz = next(s for s in tl["steps"] if s["step"] == "authorization")
    assert authz["engine"] in ("cedar", "python-mirror") and "approve allowed for Owner" in authz["result"]
    assert authz["duration_ms"] is None, "Cedar authorizations are not timed; no node duration is borrowed"
    approval = next(s for s in tl["steps"] if s["step"] == "owner approval")
    assert approval["status"] == STATUS_OK and approval["result"].startswith("approved by Dana")

    res = client.post("/v1/batch/settle", json={"payment_ids": [rheinland["id"]], "funding": "now"})
    assert res.status_code == 200, res.text
    tl = client.get(f"/v1/cards/{rheinland['id']}/timeline").json()
    names = [s["step"] for s in tl["steps"]]
    assert names[-1] == "settlement"
    settle_authz = [
        s for s in tl["steps"] if s["step"] == "authorization" and "settle allowed for System" in s["result"]
    ]
    assert settle_authz, "the Cedar settle check is on the timeline"
    assert tl["steps"][-1]["status"] == STATUS_OK and tl["steps"][-1]["engine"] == "mock"


def test_run_timeline_covers_every_card_and_unknown_ids_are_404(client):
    run_id = client.get("/v1/runs").json()[0]["id"]
    res = client.get(f"/v1/runs/{run_id}/timeline")
    assert res.status_code == 200
    body = res.json()
    assert body["run_id"] == run_id and len(body["cards"]) == 6
    assert {n["node"] for n in body["nodes"]} >= {"intake", "kernel", "score", "policy"}
    assert all(c["steps"] for c in body["cards"])
    assert client.get("/v1/runs/nope/timeline").status_code == 404
    assert client.get("/v1/cards/nope/timeline").status_code == 404


def test_builder_marks_unfinished_nodes_pending_while_running(service):
    """A run that is still executing shows the finished steps and pending placeholders for the rest."""
    from vouch.engine import Submission

    run = service.new_run([Submission(vendor_id="v-prairie", amount="1,180.00", invoice_number="PPS-9")])
    run.status = "running"
    run.emit("node_start", node="intake")
    service.intake(run)
    run.emit("node_done", node="intake", ms=7, llm_calls=0, tokens=0)
    run.emit("node_start", node="resolve")
    card = run.card_list()[0]
    tl = card_timeline(service, run, card)
    steps = _steps(tl)
    assert tl["complete"] is False
    assert steps["intake"]["status"] == STATUS_OK and steps["intake"]["duration_ms"] == 7
    assert steps["vendor screen"]["status"] == "pending" and steps["vendor screen"]["result"] == "running"
    assert steps["score"]["status"] == "pending" and steps["score"]["result"] == "queued"
    assert NODE_TIMED is not None
    assert run_timeline(service, run)["cards"][0]["card_id"] == card.id
