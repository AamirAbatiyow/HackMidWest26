"""`highlights`: the invoice rendered as document fields with red / amber / neutral severities, derived
from the kernel checks, the VouchNet features and the sender check. Additive to the payment view."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vouch import main
from vouch.audit import AuditStore
from vouch.highlights import FIELD_LABELS, highlights_of
from vouch.service import VouchService

HIGHLIGHT_KEYS = {"field", "label", "value", "severity", "reason", "reasons"}


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


def _payments(client: TestClient) -> dict[str, dict]:
    return {p["vendor"]["name"]: p for p in client.get("/v1/payments").json()}


def _by_field(payment: dict) -> dict[str, dict]:
    return {h["field"]: h for h in payment["highlights"]}


def test_every_payment_carries_a_well_formed_document(client):
    for p in _payments(client).values():
        hs = p["highlights"]
        assert hs, p["id"]
        fields = [h["field"] for h in hs]
        assert fields[:2] == ["vendor_name", "invoice_number"], "document starts with who and which invoice"
        assert len(fields) == len(set(fields)), "one row per field"
        for h in hs:
            assert set(h) == HIGHLIGHT_KEYS
            assert h["severity"] in ("ok", "warn", "high")
            assert h["label"] == FIELD_LABELS[h["field"]]
            assert isinstance(h["value"], str) and h["value"]
            if h["severity"] == "ok":
                assert h["reason"] is None and h["reasons"] == []
            else:
                assert h["reasons"] and h["reason"] == " · ".join(h["reasons"])
        # existing contract fields are untouched
        assert {"evidence", "lime", "ring", "checklist", "timeline"} <= set(p)


def test_apex_fraud_invoice_shows_the_ring_in_red(client):
    apex = _payments(client)["Apex Global Trading LLC"]
    assert apex["status"] == "verify"
    by = _by_field(apex)
    red = {f for f, h in by.items() if h["severity"] == "high"}
    assert {"bank_account", "tax_id", "amount", "address", "phone"} <= red

    bank = by["bank_account"]
    assert bank["value"] == "US071000013345"
    assert "shared with 2 other vendors" in bank["reason"]
    assert "Summit Trading Imports" in bank["reason"] and "Northgate Supply LLC" in bank["reason"]
    assert "fails checksum" in by["tax_id"]["reason"] and by["tax_id"]["value"] == "84-7712093"
    assert by["amount"]["value"] == "$12,000.00" and "round-thousand" in by["amount"]["reason"]
    assert "PO box" in by["address"]["reason"]
    assert "toll-free" in by["phone"]["reason"]
    assert by["sender_email"]["severity"] == "warn" and "webmail" in by["sender_email"]["reason"]
    assert by["vendor_name"]["severity"] == "warn" and "no payments yet" in by["vendor_name"]["reason"]
    assert by["invoice_number"]["severity"] == "ok" and by["invoice_number"]["value"] == "AGT-1007"


def test_clean_vendors_have_no_highlighted_fields(client):
    payments = _payments(client)
    for name in ("Prairie Packaging Supply", "Rheinland Gewürze GmbH", "Bao Lin Ceramics"):
        p = payments[name]
        assert p["status"] == "vouched"
        flagged = [h for h in p["highlights"] if h["severity"] != "ok"]
        assert flagged == [], f"{name}: {flagged}"
        by = _by_field(p)
        assert by["bank_account"]["value"] and by["tax_id"]["value"] and by["address"]["value"]
    # the confirmed bank change on Rheinland is not a finding
    assert _by_field(payments["Rheinland Gewürze GmbH"])["bank_account"]["reason"] is None
    # an upload has no envelope, which is neutral information rather than a flag
    assert _by_field(payments["Bao Lin Ceramics"])["sender_email"]["value"].startswith(
        "uploaded by ap-clerk-2"
    )


def test_bec_invoice_highlights_bank_sender_reply_to_and_injection(client):
    sonora = _payments(client)["Sonora Fresh Produce"]
    by = _by_field(sonora)
    assert by["bank_account"]["severity"] == "high"
    assert "differs from the account on file" in by["bank_account"]["reason"]
    assert "account in HK, vendor in MX" in by["bank_account"]["reason"]
    assert by["sender_email"]["severity"] == "high"
    assert "lookalike of sonorafresh.com" in by["sender_email"]["reason"]
    assert "failed DMARC" in by["sender_email"]["reason"]
    assert by["reply_to"]["value"] == "pagos@sonorafresh-pagos.net"
    assert "reply-to differs from sender" in by["reply_to"]["reasons"]
    assert by["remit_email"]["severity"] == "high" and "@sonorafresh.com" in by["remit_email"]["reason"]
    assert by["message"]["severity"] == "high" and "payment system" in by["message"]["reason"]
    assert by["due_date"]["severity"] == "warn" and "urgency" in by["due_date"]["reason"]
    # identity fields of a hijacked real vendor are themselves fine
    assert by["tax_id"]["severity"] == by["address"]["severity"] == by["phone"]["severity"] == "ok"


def test_duplicate_invoice_highlights_the_number(client):
    midwest = _payments(client)["Midwest Facility Services"]
    by = _by_field(midwest)
    assert by["invoice_number"]["severity"] == "high"
    assert "duplicate of paid invoice INV-2291" in by["invoice_number"]["reason"]
    assert by["po_number"]["severity"] == "warn" and by["po_number"]["value"] == "none"
    assert by["bank_account"]["severity"] == "ok"


def test_highlights_match_lime_features_and_kernel_checks(service):
    """Direct call: the red tags come from the same facts the model and policy saw."""
    from vouch.demo.story import demo_submissions
    from vouch.pipeline import execute

    run = service.new_run(demo_submissions(service.today), label="highlights")
    execute(service, run)
    apex = next(c for c in run.card_list() if c.invoice.vendor_name.startswith("Apex"))
    hs = {h["field"]: h for h in highlights_of(apex, service.vendors)}
    assert apex.features["round_amount"] == 1.0 and hs["amount"]["severity"] == "high"
    assert apex.features["tax_id_invalid"] == 1.0 and hs["tax_id"]["severity"] == "high"
    assert apex.features["shared_bank"] == 2.0 and "2 other vendors" in hs["bank_account"]["reason"]
    assert apex.checks["shared_attributes"]["bank"] == ["v-northgate", "v-summit"]
    lime_features = {row["feature"] for row in apex.scores.lime}
    assert {"shared_bank", "tax_id_invalid"} <= lime_features
