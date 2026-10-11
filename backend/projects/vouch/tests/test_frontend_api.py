"""The HTTP contract the React frontend relies on: /v1 and unversioned routes, payment shape, owner
actions, batch settlement receipts, health/info/netz, fairness, intake uploads, and error bodies."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from vouch import main
from vouch.audit import AuditStore
from vouch.demo.samples import build_samples, make_csv
from vouch.service import VouchService

PAYMENT_KEYS = {
    "id",
    "vendor",
    "invoice_number",
    "amount",
    "amount_cents",
    "due_date",
    "status",
    "lifecycle",
    "risk",
    "trust_score",
    "reason",
    "fast_pay_eligible",
    "source",
    "received_at",
    "duplicate_of",
    "split_with",
    "evidence",
    "timeline",
    "checklist",
    "ring",
    "audit_notes",
}
VENDOR_KEYS = {"id", "name", "city", "country", "since", "payments_completed"}
RECEIPT_KEYS = {
    "batch_id",
    "tx_id",
    "explorer_url",
    "settled_at",
    "funding",
    "scheduled_for",
    "total_amount",
    "lines",
    "network",
    "fee_usd",
}


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


def _by_vendor(client: TestClient, prefix: str) -> dict:
    return next(p for p in client.get("/v1/payments").json() if p["vendor"]["name"].startswith(prefix))


def test_payments_served_versioned_and_unversioned(client):
    v1 = client.get("/v1/payments")
    bare = client.get("/payments")
    assert v1.status_code == bare.status_code == 200
    assert [p["id"] for p in v1.json()] == [p["id"] for p in bare.json()]
    assert len(v1.json()) == 6


def test_payment_shape_matches_frontend_contract(client):
    payments = client.get("/v1/payments").json()
    for p in payments:
        assert set(p) >= PAYMENT_KEYS, PAYMENT_KEYS - set(p)
        assert set(p["vendor"]) >= VENDOR_KEYS
        assert p["status"] in ("vouched", "quick_check", "verify")
        assert p["lifecycle"] in ("pending", "approved", "held", "appealed", "settled")
        assert p["risk"] in ("changed_bank", "duplicate_or_split", "unrecognized_vendor", "none")
        assert 0 <= p["trust_score"] <= 100
        assert p["source"] in ("email", "upload")
        assert p["amount_cents"] == round(p["amount"] * 100)
        for ev in p["evidence"]:
            assert {"id", "label", "weight", "direction"} <= set(ev)
            assert ev["direction"] in ("reassuring", "concern"), "frontend EvidenceItem.direction"
        for item in p["timeline"]:
            assert {"id", "date", "title", "detail", "kind"} <= set(item)
        for item in p["checklist"]:
            assert {"id", "text", "done"} <= set(item)
        if p["duplicate_of"]:
            assert any(q["id"] == p["duplicate_of"] for q in payments), "duplicate_of must be a payment id"
        if p["ring"]:
            assert {"nodes", "edges"} <= set(p["ring"])
    by_name = {p["vendor"]["name"]: p for p in payments}
    assert by_name["Sonora Fresh Produce"]["status"] == "verify"
    assert by_name["Sonora Fresh Produce"]["risk"] == "changed_bank"
    assert by_name["Midwest Facility Services"]["status"] == "quick_check"
    assert by_name["Midwest Facility Services"]["risk"] == "duplicate_or_split"
    assert by_name["Prairie Packaging Supply"]["lifecycle"] == "settled"
    assert by_name["Prairie Packaging Supply"]["evidence"]
    assert "lime" in by_name["Prairie Packaging Supply"]


def test_trained_model_lime_factors_reach_the_payload(settings, tmp_path):
    """With the shipped vouch-risk bundle the scorer is local-torch and LIME rows become evidence."""
    pytest.importorskip("lime")
    from vouch.scorer import LocalScorer

    settings = settings.model_copy(
        update={"data_dir": tmp_path, "seed_demo": False, "scorer": "local", "lime_samples": 60}
    )
    scorer = LocalScorer.from_registry(settings)
    if scorer is None:
        pytest.skip("no trained vouch-risk bundle in the registry")
    service = VouchService(
        settings, store=AuditStore("sqlite://"), seed_demo=False, restore=False, scorer=scorer
    )
    service.seed(run_demo=True, background_vendors=20)
    main.set_service(service)
    try:
        client = TestClient(main.app)
        sonora = next(
            p for p in client.get("/v1/payments").json() if p["vendor"]["name"].startswith("Sonora")
        )
    finally:
        main.set_service(None)
    assert sonora["scorer"] == "local-torch" and sonora["model_version"]
    assert sonora["lime"] and {"feature", "label", "weight"} <= set(sonora["lime"][0])
    lime_labels = {row["label"] for row in sonora["lime"]}
    assert lime_labels & {ev["label"] for ev in sonora["evidence"]}, "LIME rows are surfaced as evidence"


def test_get_single_payment_and_404_body(client):
    pid = _by_vendor(client, "Rheinland")["id"]
    assert client.get(f"/v1/payments/{pid}").json()["id"] == pid
    missing = client.get("/v1/payments/nope")
    assert missing.status_code == 404
    body = missing.json()
    assert body["detail"] and body["error"]["code"] == "not_found"


def test_hold_approve_appeal_cycle(client):
    pid = _by_vendor(client, "Rheinland")["id"]
    held = client.post(f"/v1/payments/{pid}/hold", json={"note": "check discount"}).json()
    assert held["lifecycle"] == "held" and held["status"] == "quick_check"
    assert any("check discount" in n["text"] for n in held["audit_notes"])

    approved = client.post(f"/v1/payments/{pid}/approve", json={"note": "fine"}).json()
    assert approved["lifecycle"] == "approved" and approved["status"] == "vouched"
    assert approved["settlement_tx_id"] in (None, ""), "approve records the decision; no money moves yet"

    midwest = _by_vendor(client, "Midwest")
    appealed = client.post(f"/v1/payments/{midwest['id']}/appeal", json={"note": "vendor is fine"}).json()
    assert appealed["lifecycle"] == "appealed" and appealed["status"] == "vouched"
    assert appealed["trust_score"] >= 70


def test_approve_on_unknown_vendor_hold_is_refused_with_required_actions(client):
    """An unknown vendor cannot be approved away: onboarding is the only way through."""
    csv_bytes = make_csv(
        [
            ["From", "Quantum Edge Logistics"],
            ["Invoice No", "QEL-1"],
            ["Invoice Date", "2026-10-09"],
            ["Total Due", "$3,400.00"],
            ["Due Date", "2026-10-30"],
            ["IBAN", "GB29NWBK60161331926819"],
        ]
    )
    res = client.post("/v1/intake/upload", files={"files": ("qel.csv", csv_bytes, "text/csv")})
    assert res.status_code == 200, res.text
    card = res.json()["payments"][0]
    assert (
        card["status"] == "verify"
        and card["risk"] == "unrecognized_vendor"
        and card["vendor"]["match"] == "new"
    )

    res = client.post(f"/v1/payments/{card['id']}/approve", json={"note": "pay it"})
    assert res.status_code == 422
    body = res.json()
    assert "still on hold" in body["detail"]
    assert body["error"]["details"]["required_actions"]
    assert client.get(f"/v1/payments/{card['id']}").json()["lifecycle"] == "pending"


def test_apex_ring_present_for_shared_bank_card(client):
    """Apex (shared bank account) has a ring graph linking it to Summit and Northgate."""
    apex = _by_vendor(client, "Apex")
    ring = apex.get("ring")
    assert ring is not None, "Apex should have a ring (shares bank with Summit, Northgate)"
    assert {"nodes", "edges"} <= set(ring)
    node_ids = {n["id"] for n in ring["nodes"]}
    assert "v-apex" in node_ids, "Apex should be a node"
    assert any("bank" in n["id"] for n in ring["nodes"]), "ring should have a bank node"
    vendor_nodes = [n for n in ring["nodes"] if n["kind"] == "vendor"]
    assert len(vendor_nodes) >= 3, "ring should have Apex + Summit + Northgate"
    vendor_names = {n["label"] for n in vendor_nodes}
    assert "Apex Global Trading LLC" in vendor_names
    assert any("Summit" in name or "Northgate" in name for name in vendor_names)
    focus_nodes = [n for n in ring["nodes"] if n.get("focus")]
    assert len(focus_nodes) == 1 and focus_nodes[0]["id"] == "v-apex", "Apex should be the focus"
    assert ring["edges"], "ring should have edges connecting vendors to shared bank"


def test_approve_on_ring_hold_records_owner_resolution(client):
    """Apex (shared bank account ring) is owner-resolvable: approving clears the flags and logs who did it."""
    apex = _by_vendor(client, "Apex")
    assert apex["lifecycle"] == "pending" and apex["status"] == "verify"
    res = client.post(
        f"/v1/payments/{apex['id']}/approve", json={"note": "called them, verified", "author": "Dana"}
    )
    assert res.status_code == 200, res.text
    p = res.json()
    assert p["lifecycle"] == "approved" and p["settlement_tx_id"] in (None, "")
    assert any("called them" in n["text"] for n in p["audit_notes"])
    trail = client.get(f"/v1/payments/{apex['id']}/audit").json()
    assert any(a["action"] == "approve" and a["author"] == "Dana" for a in trail["store"]["approvals"])
    assert any(r["kind"] == "resolve_risk" for r in trail["resolutions"])


def test_batch_settle_returns_receipt_with_tx_ids_and_links(client):
    rhein = _by_vendor(client, "Rheinland")["id"]
    bao = _by_vendor(client, "Bao Lin")["id"]
    for pid in (rhein, bao):
        assert client.post(f"/v1/payments/{pid}/approve", json={"note": "ok"}).status_code == 200
    res = client.post("/v1/batch/settle", json={"payment_ids": [rhein, bao], "funding": "now"})
    assert res.status_code == 200, res.text
    receipt = res.json()
    assert set(receipt) >= RECEIPT_KEYS
    assert receipt["tx_id"].startswith("mock_") and receipt["simulated"] is True
    assert receipt["explorer_url"].endswith(f"/v1/receipts/{receipt['tx_id']}")
    assert receipt["total_amount"] == pytest.approx(8_880.00)
    assert {ln["payment_id"] for ln in receipt["lines"]} == {rhein, bao}
    for ln in receipt["lines"]:
        assert {"payment_id", "vendor_name", "invoice_number", "amount", "tx_id", "explorer_url"} <= set(ln)
        assert ln["tx_id"]
    for pid in (rhein, bao):
        p = client.get(f"/v1/payments/{pid}").json()
        assert p["lifecycle"] == "settled" and p["settlement_tx_id"] and p["explorer_url"]
    stored = client.get(f"/v1/receipts/{receipt['tx_id']}")
    assert stored.status_code == 200
    record = stored.json()
    assert record["tx_id"] == receipt["tx_id"] and record["card_id"] in (rhein, bao)
    assert record["stored"] and record["stored"][0]["tx_id"] == receipt["tx_id"]
    assert client.get("/v1/receipts/mock_nope").status_code == 404


def test_batch_settle_refuses_held_and_unapproved_cards(client):
    sonora = _by_vendor(client, "Sonora")["id"]
    res = client.post("/v1/batch/settle", json={"payment_ids": [sonora], "funding": "now"})
    assert res.status_code == 422 and "on hold" in res.json()["detail"]
    assert client.get(f"/v1/payments/{sonora}").json()["lifecycle"] == "pending"


def test_scheduled_funding_keeps_cards_approved(client):
    rhein = _by_vendor(client, "Rheinland")["id"]
    client.post(f"/v1/payments/{rhein}/approve", json={"note": "ok"})
    receipt = client.post("/v1/batch/settle", json={"payment_ids": [rhein], "funding": "scheduled"}).json()
    assert receipt["funding"] == "scheduled" and receipt["scheduled_for"] and receipt["tx_id"] == ""
    p = client.get(f"/v1/payments/{rhein}").json()
    assert p["lifecycle"] == "approved" and p["funding"]["pay_on"]


def test_health_json_html_and_cheap_probe(client):
    j = client.get("/health").json()
    assert j["status"] in ("ok", "degraded") and j["service"] == "vouch-api"
    assert {"settlement_adapter", "scorer", "version", "errors"} <= set(j)
    for role in ("inference", "embeddings", "database", "settlement", "risk_model", "policy_engine"):
        assert j[role]["state"] in ("live", "fallback", "off", "error") and j[role]["akamai_service"], role
    assert j["settlement"]["state"] == "fallback", "mock ledger is the simulated fallback"
    assert j["policy_engine"]["state"] in ("live", "fallback"), "cedarpy (live) or Python mirror (fallback)"
    html = client.get("/health", headers={"Accept": "text/html"})
    assert html.status_code == 200 and html.headers["content-type"].startswith("text/html")
    assert "Vouch" in html.text and "Akamai" in html.text
    probe = client.get("/v1/health").json()
    assert probe["status"] == "ok" and probe["service"] == "vouch-api" and "uptime_s" in probe


def test_info_netz_fairness_shapes(client):
    info = client.get("/v1/info").json()
    assert {"model", "policy_mode", "version", "settlement_adapter", "llm_mode"} <= set(info)
    assert info["policy_mode"] in ("cedar", "python-mirror")
    assert client.get("/info").json()["version"] == info["version"]

    netz = client.get("/v1/netz").json()
    assert {"hops", "model_version", "tokens", "policy_checks", "region", "updated_at"} <= set(netz)
    assert netz["hops"] and {"id", "from", "to", "p50_ms", "p95_ms", "private"} <= set(netz["hops"][0])
    assert netz["policy_checks"]["total"] >= netz["policy_checks"]["passed"]
    assert client.get("/netz").status_code == 200

    fairness = client.get("/v1/fairness")
    assert fairness.status_code == 200
    assert all(("_" not in k) or k == "model_metrics" or k == "model_version" for k in fairness.json())


def test_intake_json_eml_and_upload_endpoints(client):
    samples = {s.key: s for s in build_samples(datetime(2026, 10, 10, 15, 0, tzinfo=UTC))}

    body = samples["prairie"].request.model_dump(mode="json")
    res = client.post("/v1/intake", json=body)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["run"]["id"] and out["payments"][0]["vendor"]["name"] == "Prairie Packaging Supply"
    assert out["payments"][0]["source"] == "email"

    eml_name, eml = next((n, b) for n, b in samples["apex"].files.items() if n.endswith(".eml"))
    res = client.post(
        "/v1/intake/eml", files={"file": (eml_name, eml, "message/rfc822")}, data={"submitted_by": "t"}
    )
    assert res.status_code == 200, res.text
    apex = res.json()["payments"][0]
    assert apex["status"] == "verify" and apex["lifecycle"] == "pending" and apex["sender"]["flags"]

    csv_bytes = make_csv(
        [
            ["field", "value"],
            ["From", "Bao Lin Ceramics"],
            ["Invoice No", "BLC-0099"],
            ["Invoice Date", "2026-10-09"],
            ["Total Due", "$640.00"],
            ["Due Date", "2026-10-30"],
            ["Bank account", "VN123456789012"],
        ]
    )
    res = client.post(
        "/v1/intake/upload",
        files={"files": ("blc.csv", csv_bytes, "text/csv")},
        data={"submitted_by": "clerk", "delivery_confirmed": "true"},
    )
    assert res.status_code == 200, res.text
    uploaded = res.json()["payments"][0]
    assert uploaded["source"] == "upload" and uploaded["invoice_number"] == "BLC-0099"
    assert uploaded["amount_cents"] == 64_000

    empty = client.post("/v1/intake", json={"body_text": "   "})
    assert empty.status_code == 422 and empty.json()["detail"]


def test_vendor_resolve_and_sender_check_endpoints(client):
    res = client.post("/v1/vendors/resolve", json={"name": "Prairie Packing Supplies"}).json()
    assert res["status"] == "uncertain" and res["candidates"][0]["vendor_id"] == "v-prairie"
    known = client.post("/v1/vendors/resolve", json={"name": "x", "email": "ar@prairiepackaging.com"}).json()
    assert known["status"] == "known" and known["vendor_id"] == "v-prairie"

    headers = {
        "From": "Prairie Packaging AR <ar@prairiepackaging-billing.com>",
        "Reply-To": "ar@prairie-remit.net",
        "Authentication-Results": "mx; spf=softfail smtp.mailfrom=prairiepackaging-billing.com; dkim=none; dmarc=fail",
    }
    check = client.post(
        "/v1/sender/check", json={"headers": headers, "claimed_vendor_id": "v-prairie"}
    ).json()
    assert check["suspicious"] is True and "lookalike_domain" in check["flags"]


def test_attachment_roundtrip_in_json_intake(client):
    data = make_csv(
        [
            ["From", "Rheinland Gewürze GmbH"],
            ["Invoice No", "RG-77"],
            ["Invoice Date", "2026-10-09"],
            ["Total Due", "$120.00"],
            ["Due Date", "2026-11-01"],
        ]
    )
    body = {
        "source": "upload",
        "attachments": [
            {"filename": "rg.csv", "content_type": "text/csv", "data_b64": base64.b64encode(data).decode()}
        ],
    }
    res = client.post("/v1/intake", json=body)
    assert res.status_code == 200, res.text
    p = res.json()["payments"][0]
    assert p["invoice_number"] == "RG-77" and p["amount_cents"] == 12_000
