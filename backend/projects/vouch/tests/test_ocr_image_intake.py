"""Image invoices (PNG) through the real extraction path, and what happens on a host without an OCR engine.

The live Akamai container once shipped without the tesseract binary: every emailed PNG came out as
amount 0 with "submission could not be read". These tests pin both halves of the fix: with tesseract the
invoice-creator's PNGs parse (amount, vendor, invoice number, bank details); without it the card and
/v1/health name the missing engine instead of blaming the sender.
"""

from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vouch import main
from vouch.audit import AuditStore
from vouch.contracts import Attachment, IntakeRequest
from vouch.demo.samples import make_png
from vouch.domain import CardStatus, Lane
from vouch.intake import claims, extract
from vouch.kernel import parse_invoice_text
from vouch.policy import R_INJECTION, R_KICKBACK, R_OCR_MISSING
from vouch.service import VouchService

INVOICE_CREATOR = Path(__file__).resolve().parents[4] / "demo-tools" / "invoice-creator"
OWNER = ("Grand Avenue Trading LLC", "Kansas City, MO")

NO_ENGINE = {"backend": "none", "version": None, "languages": [], "binary": None}
TESSERACT = {"backend": "tesseract", "version": "5.3.4", "languages": ["eng"], "binary": "/usr/bin/tesseract"}


def _invoice_creator():
    """The demo tool is a sibling package, not a workspace member: import it from the repo checkout."""
    if not (INVOICE_CREATOR / "invoice_creator").is_dir():
        pytest.skip("demo-tools/invoice-creator not present in this checkout")
    if str(INVOICE_CREATOR) not in sys.path:
        sys.path.insert(0, str(INVOICE_CREATOR))
    presets = pytest.importorskip("invoice_creator.presets")
    render = pytest.importorskip("invoice_creator.render")
    return presets, render


def _png_attachment(data: bytes, name: str = "invoice.png") -> Attachment:
    return Attachment(filename=name, content_type="image/png", data_b64=base64.b64encode(data).decode())


@pytest.fixture
def svc(settings, tmp_path):
    settings = settings.model_copy(update={"data_dir": tmp_path, "seed_demo": False})
    service = VouchService(settings, store=AuditStore("sqlite://"), seed_demo=False, restore=False)
    service.seed(run_demo=False, background_vendors=40)
    return service


@pytest.fixture
def client(svc):
    main.set_service(svc)
    try:
        yield TestClient(main.app)
    finally:
        main.set_service(None)


@pytest.fixture
def ocr_probe(monkeypatch):
    """Pin what the OCR probe reports and clear its cache (restored on teardown)."""

    def pin(info: dict) -> None:
        monkeypatch.setattr(extract, "_probe_ocr", lambda: dict(info))
        monkeypatch.setattr(extract, "_ocr_cache", None)
        monkeypatch.setattr(extract, "_ocr_probed_at", 0.0)

    yield pin
    # a later test must probe the real host again, not a leftover of the pinned answer
    monkeypatch.setattr(extract, "_ocr_cache", None)


# ------------------------------------------------------------- with an OCR engine (tesseract) ----

needs_ocr = pytest.mark.skipif(
    extract.ocr_backend() == "none",
    reason="no OCR engine installed (apt-get install tesseract-ocr tesseract-ocr-eng)",
)

# clean (fast-pay lane) and fraudulent (vendor ring / BEC) presets from the invoice creator
PRESETS = ["prairie", "apex", "sonora", "baolin"]


@needs_ocr
@pytest.mark.parametrize("key", PRESETS)
def test_invoice_creator_png_parses_amount_vendor_number_and_bank(key):
    presets, render = _invoice_creator()
    inv = presets.get_preset(key).invoice
    png = render.render_png(inv, *OWNER)
    doc = extract.extract_file(png, f"{inv.invoice_number}.png", "image/png")
    assert doc.kind == "image" and doc.extractor.startswith("ocr:") and not doc.warnings, doc.warnings
    fields = parse_invoice_text(doc.text).fields
    assert fields["amount_cents"] == round(inv.amount * 100), (key, doc.text)
    assert fields["invoice_number"] == inv.invoice_number, key
    assert fields["vendor_name"].lower().startswith(inv.vendor_name.lower()[:12]), (
        key,
        fields["vendor_name"],
    )
    claim = claims.extract_claim(doc.text)
    assert claim.bank_account == re.sub(r"\s+", "", inv.bank.account_number), key


@needs_ocr
def test_invoice_creator_pngs_land_in_their_lanes_through_intake(svc):
    presets, render = _invoice_creator()
    prairie = presets.get_preset("prairie")
    run = svc.intake(
        IntakeRequest(
            attachments=[_png_attachment(render.render_png(prairie.invoice, *OWNER), "PPS-2211.png")],
            source="upload",
            delivery_confirmed=True,
            po_number=prairie.invoice.po_number,
        )
    )
    card = run.card_list()[0]
    assert card.invoice.amount_cents == 121_500 and card.invoice.invoice_number == "PPS-2211"
    assert card.invoice.vendor_id == "v-prairie" and card.intake and not card.intake.kickback
    assert card.policy and card.policy.lane != Lane.HOLD, card.policy

    apex = presets.get_preset("apex")
    run = svc.intake(
        IntakeRequest(
            attachments=[_png_attachment(render.render_png(apex.invoice, *OWNER), "AGT-1008.png")],
            source="upload",
        )
    )
    card = run.card_list()[0]
    assert card.invoice.amount_cents == 1_200_000 and card.invoice.invoice_number == "AGT-1008"
    assert card.invoice.bank_account == apex.invoice.bank.account_number
    assert card.intake and not card.intake.kickback, "the fraud is caught by the kernel, not by unreadability"
    assert card.policy and card.policy.lane == Lane.HOLD and R_OCR_MISSING not in card.policy.reasons

    # BEC attempt: the injection lives only in the invoice notes, which the PNG must carry in full
    sonora = presets.get_preset("sonora")
    run = svc.intake(
        IntakeRequest(
            attachments=[_png_attachment(render.render_png(sonora.invoice, *OWNER), "SFP-88219.png")],
            source="upload",
        )
    )
    card = run.card_list()[0]
    assert card.invoice.amount_cents == 985_000 and card.invoice.invoice_number == "SFP-88219"
    assert card.checks.get("injection"), "the 'pre-approved / skip the review' note survived OCR"
    assert card.policy and card.policy.lane == Lane.HOLD and R_INJECTION in card.policy.reasons


# ------------------------------------------------------------------ without an OCR engine ----


def test_missing_engine_is_named_on_the_card_not_blamed_on_the_sender(svc, ocr_probe):
    ocr_probe(NO_ENGINE)
    png = make_png(["From: Prairie Packaging Supply", "Invoice No: PPS-5001", "Total Due: $1,180.00"])
    run = svc.intake(IntakeRequest(attachments=[_png_attachment(png)], source="email"))
    card = run.card_list()[0]
    assert card.invoice.amount_cents == 0 and card.status == CardStatus.HOLD
    assert card.intake and card.intake.kickback and card.intake.kickback_code == "unreadable_scan"
    assert card.intake.ocr_unavailable is True
    assert "no OCR engine installed on this server" in (card.intake.kickback_reason or "")
    assert card.policy and card.policy.reasons[0] == R_OCR_MISSING and R_KICKBACK in card.policy.reasons
    view = svc.payment(card.id)
    assert "no OCR engine" in view["reason"] and "tesseract" in view["reason"]
    assert "tesseract-ocr" in view["checklist"][0]["text"]
    assert view["policy_reasons"][0] == R_OCR_MISSING and view["intake"]["ocr_unavailable"] is True
    docs = [d for d in run.submissions[0].documents if d.get("kind") == "image"]
    assert docs and any("tesseract-ocr" in w for w in docs[0]["warnings"])


def test_with_an_engine_an_unreadable_scan_is_not_blamed_on_the_server(svc, ocr_probe, monkeypatch):
    ocr_probe(TESSERACT)
    monkeypatch.setattr(extract, "extract_image", lambda data, filename: extract.extract_text(b"", filename))
    png = make_png(["blank"])
    run = svc.intake(IntakeRequest(attachments=[_png_attachment(png, "scan.png")], source="email"))
    card = run.card_list()[0]
    assert card.intake and card.intake.kickback and card.intake.ocr_unavailable is False
    assert card.policy and R_OCR_MISSING not in card.policy.reasons and R_KICKBACK in card.policy.reasons


def test_health_reports_ocr_down_then_live_without_a_restart(client, ocr_probe, monkeypatch):
    ocr_probe(NO_ENGINE)
    probe = client.get("/v1/health").json()
    assert probe["status"] == "ok", "liveness stays ok; the OCR gap is reported, not fatal"
    assert probe["ocr"] == {"state": "down", "backend": "none", "tesseract_version": None, "languages": []}
    full = client.get("/health").json()
    assert full["status"] == "degraded" and "ocr" in full["errors"]
    assert full["ocr"]["state"] == "down" and "tesseract-ocr" in full["ocr"]["detail"]
    html = client.get("/health", headers={"Accept": "text/html"}).text
    assert "down" in html and "tesseract" in html

    # `apt-get install tesseract-ocr` in the running container: the negative answer is re-checked
    monkeypatch.setattr(extract, "OCR_RECHECK_S", 0.0)
    monkeypatch.setattr(extract, "_probe_ocr", lambda: dict(TESSERACT))
    probe = client.get("/v1/health").json()
    assert probe["ocr"]["state"] == "live" and probe["ocr"]["tesseract_version"] == "5.3.4"
    assert probe["ocr"]["languages"] == ["eng"]
    full = client.get("/health").json()
    assert full["ocr"]["state"] == "live" and "5.3.4" in full["ocr"]["detail"] and "ocr" not in full["errors"]
    assert full["ocr"]["tesseract_version"] == "5.3.4"

    # a found engine is remembered: the binary is not looked for on every 5-second poll
    monkeypatch.setattr(extract, "_probe_ocr", lambda: dict(NO_ENGINE))
    assert client.get("/v1/health").json()["ocr"]["state"] == "live"


def test_tesseract_without_language_data_is_down(client, ocr_probe):
    ocr_probe({**TESSERACT, "languages": []})
    probe = client.get("/v1/health").json()
    assert probe["ocr"]["state"] == "down" and probe["ocr"]["tesseract_version"] == "5.3.4"
    assert "tesseract-ocr-eng" in client.get("/health").json()["ocr"]["detail"]


def test_v1_health_ocr_entry_is_additive(client):
    probe = client.get("/v1/health").json()
    assert {"status", "service", "version", "uptime_s", "ocr"} <= set(probe)
    assert probe["ocr"]["state"] in ("live", "down")
    assert probe["ocr"]["backend"] == extract.ocr_backend()
