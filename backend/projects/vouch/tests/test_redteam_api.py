import pytest
from fastapi.testclient import TestClient

from vouch import main
from vouch.redteam import CASES, run_suite
from vouch.scorer import HeuristicScorer


def test_redteam_suite_blocks_every_attack(settings):
    result = run_suite(settings, scorer=HeuristicScorer())
    failed = [(c["id"], c["error"], c["detail"]) for c in result["cases"] if not c["blocked"]]
    assert not failed, failed
    assert result["total"] == len(CASES) >= 15


@pytest.fixture
def client(service):
    main.set_service(service)
    main._state["redteam"] = None
    yield TestClient(main.app)
    main.set_service(None)


def test_api_demo_flow(client):
    assert client.get("/health").json()["service"] == "vouch-api"
    info = client.get("/v1/info").json()
    assert info["settlement_adapter"] == "mock" and info["scorer"] == "heuristic-fallback"

    run = client.post("/v1/demo/seed").json()["run"]
    assert run["status"] == "awaiting_approval" and run["totals"]["lanes"] == {
        "fast_pay": 1,
        "standard": 2,
        "hold": 3,
    }
    rid = run["id"]

    cards = client.get("/v1/cards", params={"run_id": rid}).json()
    assert len(cards) == 6
    for c in cards:
        assert {
            "risk_class",
            "risk",
            "legitimacy",
            "lime",
            "policy_reasons",
            "explanation",
            "funding",
        } <= c.keys()
    held = client.get("/v1/cards", params={"lane": "hold"}).json()
    sonora = next(c for c in held if c["vendor"].startswith("Sonora"))

    full = client.get(f"/v1/cards/{sonora['id']}").json()
    assert full["facts"]["phone_on_file"] == "+52-662-555-0199"

    r = client.post(f"/v1/cards/{sonora['id']}/confirm-bank", json={"phone_called": "+852 5550 1234"})
    assert r.status_code == 422
    assert client.post(f"/v1/cards/{sonora['id']}/approve", json={}).status_code == 422

    settled = client.post(f"/v1/runs/{rid}/approve", json={"approved": True, "approver": "dana"}).json()
    assert settled["status"] == "completed" and settled["totals"]["paid_cents"] == 118_000 + 824_000 + 64_000
    txs = [p["tx_id"] for s in settled["settlements"] for p in s["payments"]]
    assert len(txs) == 3 and all(t.startswith("mock_") for t in txs)

    events = client.get(f"/v1/runs/{rid}/events").json()["events"]
    assert {"node_start", "awaiting_approval", "owner_decision", "settled"} <= {e["type"] for e in events}
    stream = client.get(f"/v1/runs/{rid}/stream")
    assert "event: settled" in stream.text and "event: end" in stream.text

    netz = client.get("/v1/netz").json()
    assert netz["llm"]["limits"]["rpm"] == 60 and "node:score" in netz["latency"]
    assert client.get("/v1/cash").json()["forecast"]["buffer_cents"] > 0


def test_api_submit_text_and_json(client):
    client.post("/v1/demo/seed", params={"run": "false"})
    text = "From: Prairie Packaging Supply\nInvoice No: PPS-3001\nTotal Due: $640.00\nDue Date: 2026-10-30\n"
    run = client.post(
        "/v1/invoices/text", json={"text": text, "po_number": "PO-1", "delivery_confirmed": True}
    ).json()
    card = run["cards"][0]
    assert card["amount_cents"] == 64_000 and card["vendor"] == "Prairie Packaging Supply"

    body = {
        "invoices": [
            {
                "vendor_id": "v-rheinland",
                "invoice_number": "RG-77",
                "amount": "7,100.00",
                "issue_date": "2026-10-09",
                "due_date": "2026-11-01",
                "po_number": "PO-2",
                "delivery_confirmed": True,
            }
        ]
    }
    run = client.post("/v1/invoices", json=body).json()
    assert run["cards"][0]["lane"] == "standard"
    assert (
        client.post(
            "/v1/invoices", json={"invoices": [{"vendor_id": "v-rheinland", "amount": "9,9OO.00"}]}
        ).status_code
        == 422
    )


def test_api_redteam_endpoint(client):
    body = client.get("/v1/redteam").json()
    assert body["all_blocked"], [c for c in body["cases"] if not c["blocked"]]
