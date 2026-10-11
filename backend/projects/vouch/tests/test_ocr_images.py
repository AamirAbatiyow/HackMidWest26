"""Image invoices (PNG) through the real OCR path, and what the card and health endpoints say when the
server has no OCR engine (the live-deploy failure: python:*-slim without tesseract -> amount 0).

The tesseract-backed tests skip cleanly where the binary is absent; the "no engine" tests run everywhere.
"""

from __future__ import annotations

import base64
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vouch import main
from vouch.audit import AuditStore
from vouch.contracts import Attachment, IntakeRequest
from vouch.demo.samples import make_png
from vouch.domain import CardStatus, Lane
from vouch.intake import extract
from vouch.policy import R_KICKBACK, R_OCR_UNAVAILABLE, R_RING
from vouch.service import VouchService

needs_tesseract = pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="tesseract binary not installed (apt-get install tesseract-ocr tesseract-ocr-eng)",
)

# demo-tools/invoice-creator in the monorepo: the operator tool whose PNGs the live deploy receives.
INVOICE_CREATOR = Path(__file__).resolve().parents[4] / "demo-tools" / "invoice-creator"

PRAIRIE_LINES = [
    "Prairie Packaging Supply",
    "From: Prairie Packaging Supply",
    "2210 N Industrial Blvd, Wichita, KS",
    "Email: ar@prairiepackaging.com    Phone: +1-316-555-0142",
    "",
    "INVOICE",
    "Invoice No: PPS-2211",
    "Invoice Date: 2026-10-08",
    "Due Date: 2026-10-22",
    "PO Number: PO-48790",
    "Bill To: Heartland Provisions Co., Kansas City, MO",
    "",
    "Subtotal: $1,215.00",
    "Total Due: $1,215.00 USD",
    "",
    "Payment Details",
    "Bank Name: Intrust Bank, Wichita",
    "Account Number: US021000089912",
]


@pytest.fixture
def svc(settings, tmp_path):
    s = settings.model_copy(update={"data_dir": tmp_path, "seed_demo": False})
    service = VouchService(s, store=AuditStore("sqlite://"), seed_demo=False, restore=False)
    service.seed(run_demo=False, background_vendors=40)
    main.set_service(service)
    return service


@pytest.fixture
def no_ocr(monkeypatch):
    """The deployed container before the fix: pytesseract importable, no `tesseract` binary, no rapidocr."""
    saved = dict(extract._ocr_cache)
    monkeypatch.setattr(extract, "_probe_ocr_backend", lambda: "none")
    extract._ocr_cache.clear()
    extract._live_ocr_status.cache_clear()
    yield
    extract._ocr_cache.clear()
    extract._ocr_cache.update(saved)
    extract._live_ocr_status.cache_clear()


def _att(filename: str, content_type: str, data: bytes) -> Attachment:
    return Attachment(filename=filename, content_type=content_type, data_b64=base64.b64encode(data).decode())


def _email(body: str, *attachments: Attachment, sender: str = "Prairie AR <ar@prairiepackaging.com>"):
    return IntakeRequest(
        source="email",
        headers={"From": sender, "Subject": "Invoice attached"},
        body_text=body,
        attachments=list(attachments),
    )


# ------------------------------------------------------------------ no engine: visible, not silent ----


def test_missing_ocr_engine_is_named_on_the_card_and_in_health(svc, no_ocr):
    """Before: amount 0 and a generic "submission could not be read" with the cause buried in a document
    warning. Now the first hold reason and the first checklist item say the server has no OCR engine."""
    assert extract.ocr_status()["state"] == "down"
    run = svc.intake(
        _email(
            "Invoice PPS-2211 attached, thanks.", _att("PPS-2211.png", "image/png", make_png(PRAIRIE_LINES))
        )
    )
    card = run.card_list()[0]
    assert card.status == CardStatus.HOLD and card.policy and card.policy.lane == Lane.HOLD
    assert card.invoice.amount_cents == 0, "nothing was read, so nothing can be paid"
    assert card.policy.reasons[0] == R_OCR_UNAVAILABLE and R_KICKBACK in card.policy.reasons
    assert "tesseract-ocr" in card.policy.required_actions[0]
    assert card.intake and card.intake.ocr_unavailable
    assert "no OCR engine installed on this server" in (card.intake.kickback_reason or "")
    doc = next(d for d in run.submissions[0].documents if d["filename"] == "PPS-2211.png")
    assert doc["extractor"] == "ocr:none" and any("no OCR engine" in w for w in doc["warnings"])

    view = svc.payment(card.id)
    assert view["policy_reasons"][0] == R_OCR_UNAVAILABLE
    assert "tesseract-ocr" in view["checklist"][0]["text"]
    assert "no OCR engine" in view["reason"]
    assert view["status"] == "quick_check", "a server fault is paperwork, not an identity problem"

    with TestClient(main.app) as client:
        probe = client.get("/v1/health").json()
        assert probe["status"] == "ok", "liveness stays green: the NodeBalancer check must not flap"
        assert probe["ocr"]["state"] == "down" and probe["ocr"]["backend"] == "none"
        assert "tesseract-ocr" in probe["ocr"]["detail"]
        health = client.get("/health?format=json").json()
        assert health["ocr"]["state"] == "error" and "ocr" in health["errors"]


def test_installing_the_engine_into_the_running_container_needs_no_restart(svc, no_ocr, monkeypatch):
    """The no-downtime fix path: `apt-get install tesseract-ocr` inside the live container. A missing engine
    is re-probed per call (never memoised), so the classifier and the health poll flip without a restart."""
    assert extract.ocr_backend() == "none" and not svc.engine.classifier.ocr_available()
    with TestClient(main.app) as client:
        assert client.get("/v1/health").json()["ocr"]["state"] == "down"
    monkeypatch.setattr(extract, "_probe_ocr_backend", lambda: "tesseract")
    monkeypatch.setattr(extract, "_live_ocr_status", _fake_live_status)
    assert extract.ocr_backend() == "tesseract" and svc.engine.classifier.ocr_available()
    with TestClient(main.app) as client:
        assert client.get("/v1/health").json()["ocr"] == {
            "state": "live",
            "backend": "tesseract",
            "tesseract_version": "5.3.0",
            "languages": ["eng"],
            "detail": "tesseract 5.3.0 · languages eng",
        }


def _fake_live_status() -> dict:
    return {
        "state": "live",
        "backend": "tesseract",
        "tesseract_version": "5.3.0",
        "languages": ["eng"],
        "detail": "tesseract 5.3.0 · languages eng",
    }


_fake_live_status.cache_clear = lambda: None  # type: ignore[attr-defined]


def test_a_readable_pdf_does_not_carry_the_ocr_reason(svc, no_ocr):
    from vouch.demo.samples import make_pdf

    run = svc.intake(_email("", _att("inv.pdf", "application/pdf", make_pdf(PRAIRIE_LINES, "Invoice"))))
    card = run.card_list()[0]
    assert card.invoice.amount_cents == 121_500
    assert not (card.intake and card.intake.ocr_unavailable)
    assert not card.policy or R_OCR_UNAVAILABLE not in card.policy.reasons


# ------------------------------------------------------------------------- tesseract: real OCR ----


@needs_tesseract
def test_ocr_status_reports_tesseract_and_english_data():
    extract._live_ocr_status.cache_clear()
    status = extract.ocr_status()
    assert status["state"] == "live" and status["backend"] == "tesseract"
    assert status["tesseract_version"] and status["tesseract_version"][0].isdigit()
    assert "eng" in status["languages"]
    with TestClient(main.app) as client:
        assert client.get("/v1/health").json()["ocr"]["tesseract_version"] == status["tesseract_version"]


@needs_tesseract
def test_png_invoice_is_ocrd_and_the_kernel_parses_it(svc):
    doc = extract.extract_file(make_png(PRAIRIE_LINES), "PPS-2211.png", "image/png")
    assert doc.extractor == "ocr:tesseract" and not doc.warnings
    for needle in ("Invoice No: PPS-2211", "Total Due: $1,215.00", "US021000089912"):
        assert needle in doc.text, (needle, doc.text)

    run = svc.intake(_email("Invoice attached.", _att("PPS-2211.png", "image/png", make_png(PRAIRIE_LINES))))
    card = run.card_list()[0]
    inv = card.invoice
    assert inv.vendor_id == "v-prairie" and inv.invoice_number == "PPS-2211"
    assert inv.amount_cents == 121_500 and inv.amount_origin == "source"
    assert inv.bank_account == "US021000089912"
    assert card.policy and card.policy.lane == Lane.FAST_PAY
    assert card.status in (CardStatus.PAID, CardStatus.READY)
    assert card.policy.reasons and R_OCR_UNAVAILABLE not in card.policy.reasons


@needs_tesseract
@pytest.mark.skipif(not INVOICE_CREATOR.is_dir(), reason="demo-tools/invoice-creator not checked out")
def test_invoice_creator_png_emails_parse_through_intake(svc, monkeypatch):
    """The operator tool's PNG output (clean Prairie preset and the Apex fraud-ring preset), as the .eml
    the mail receiver forwards, through the real path: OCR -> kernel -> vendor -> policy."""
    monkeypatch.syspath_prepend(str(INVOICE_CREATOR))
    monkeypatch.setenv("DEMO_SKIP_DOTENV", "1")
    presets = pytest.importorskip("invoice_creator.presets")
    mail = pytest.importorskip("invoice_creator.mail")
    config = pytest.importorskip("invoice_creator.config")
    models = pytest.importorskip("invoice_creator.models")
    demo = config.load_settings()

    def eml(key: str) -> tuple[bytes, object]:
        p = presets.get_preset(key)
        req = models.SendRequest(invoice=p.invoice, sender=p.sender, format="png", delivery="none")
        msg, attachment = mail.build_message(req, demo)
        assert attachment is not None and attachment.content_type == "image/png"
        return mail.message_bytes(msg), p.invoice

    raw, prairie = eml("prairie")
    card = svc.intake_eml(raw).card_list()[0]
    assert card.invoice.vendor_id == "v-prairie" and card.invoice.vendor_name == prairie.vendor_name
    assert card.invoice.invoice_number == prairie.invoice_number
    assert card.invoice.amount_cents == round(prairie.amount * 100) and card.invoice.amount_origin == "source"
    assert card.invoice.bank_account == prairie.bank.account_number
    assert card.policy and card.policy.lane == Lane.FAST_PAY

    raw, apex = eml("apex")
    card = svc.intake_eml(raw).card_list()[0]
    assert card.invoice.vendor_name == apex.vendor_name and card.invoice.invoice_number == apex.invoice_number
    assert card.invoice.amount_cents == round(apex.amount * 100) and card.invoice.amount_origin == "source"
    assert card.invoice.bank_account == apex.bank.account_number
    assert card.policy and card.policy.lane == Lane.HOLD and R_RING in card.policy.reasons
    assert R_OCR_UNAVAILABLE not in card.policy.reasons and R_KICKBACK not in card.policy.reasons
