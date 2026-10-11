"""Intake: file extraction (PDF / XLSX / CSV / text / .eml), deterministic claims, and the six synthetic
sample invoices flowing through `VouchService.intake` into their expected lanes."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest

from vouch.audit import AuditStore
from vouch.contracts import Attachment, IntakeRequest
from vouch.demo.samples import build_samples, make_csv, make_eml, make_pdf, make_xlsx
from vouch.domain import CardStatus, Lane
from vouch.intake import claims, email_parse, extract
from vouch.kernel import parse_invoice_text
from vouch.service import VouchService

INVOICE_LINES = [
    "From: Prairie Packaging Supply",
    "Invoice No: PPS-5001",
    "Invoice Date: 2026-10-07",
    "Bill to: Heartland Provisions Co.",
    "Total Due: $1,180.00",
    "Due Date: 2026-10-30",
    "IBAN: US021000089912",
    "Tax ID: 48-1234567",
]


def _fields(text: str) -> dict:
    return parse_invoice_text(text).fields


def test_pdf_extraction_keeps_labels_and_amounts():
    doc = extract.extract_file(make_pdf(INVOICE_LINES, "Invoice PPS-5001"), "invoice.pdf", "application/pdf")
    assert doc.kind == "pdf" and doc.sha256
    fields = _fields(doc.text)
    assert fields["vendor_name"].startswith("Prairie Packaging Supply")
    assert fields["invoice_number"] == "PPS-5001"
    assert fields["amount_cents"] == 118_000


@pytest.mark.parametrize("maker,ext", [(make_csv, "csv"), (make_xlsx, "xlsx")])
def test_key_value_sheets_parse_like_labelled_text(maker, ext):
    rows = [["field", "value"]] + [ln.split(": ", 1) for ln in INVOICE_LINES]
    doc = extract.extract_file(maker(rows), f"invoice.{ext}")
    assert doc.kind == ext and doc.tables and len(doc.tables[0].rows) == len(rows)
    fields = _fields(doc.text)
    assert fields["vendor_name"] == "Prairie Packaging Supply"
    assert fields["invoice_number"] == "PPS-5001"
    assert fields["amount_cents"] == 118_000
    assert fields["due_date"].isoformat() == "2026-10-30"


def test_unknown_type_falls_back_to_text_with_warning():
    doc = extract.extract_file(b"Total Due: $12.00", "weird.bin", "application/octet-stream")
    assert doc.kind == "unknown" and doc.warnings and "$12.00" in doc.text


def test_combine_documents_marks_sources():
    a = extract.extract_text(b"Invoice No: A-1", "body.txt")
    b = extract.extract_file(make_csv([["Total Due", "$5.00"]]), "x.csv")
    text = extract.combine_documents([a, b])
    assert "[[ text: body.txt ]]" in text and "[[ csv: x.csv ]]" in text and "[[ table: x.csv ]]" in text


def test_claim_extraction_is_deterministic_and_code_owned():
    claim = claims.extract_claim("\n".join(INVOICE_LINES), sender_email="ar@prairiepackaging.com")
    assert claim.name == "Prairie Packaging Supply"
    assert claim.bank_account == "US021000089912"
    assert claim.tax_id == "48-1234567"
    assert claim.email == "ar@prairiepackaging.com"


def test_parse_eml_envelope_and_attachments():
    pdf = make_pdf(INVOICE_LINES, "Invoice")
    headers = {
        "From": "Prairie Packaging AR <ar@prairiepackaging.com>",
        "To": "ap@heartlandprovisions.example",
        "Subject": "Invoice PPS-5001",
        "Reply-To": "ar@prairiepackaging.com",
        "Date": "Wed, 07 Oct 2026 14:00:00 +0000",
        "Message-ID": "<abc@prairiepackaging.com>",
        "Authentication-Results": "mx; spf=pass smtp.mailfrom=prairiepackaging.com; dkim=pass header.d=prairiepackaging.com; dmarc=pass",
    }
    req = email_parse.parse_eml(
        make_eml(
            headers, "Invoice attached.\n" + "\n".join(INVOICE_LINES), [("inv.pdf", "application/pdf", pdf)]
        )
    )
    assert req.source == "email"
    assert [a.filename for a in req.attachments] == ["inv.pdf"]
    assert base64.b64decode(req.attachments[0].data_b64) == pdf
    env = email_parse.envelope_from_headers(req.headers)
    assert env.from_addr == "ar@prairiepackaging.com" and env.from_name == "Prairie Packaging AR"
    assert env.authentication_results and "dmarc=pass" in env.authentication_results[0]
    assert "Total Due" in email_parse.intake_body_text(req)


# ------------------------------------------------------------ service-level intake -----------------------


@pytest.fixture
def svc(settings, tmp_path):
    settings = settings.model_copy(update={"data_dir": tmp_path, "seed_demo": False})
    service = VouchService(settings, store=AuditStore("sqlite://"), seed_demo=False, restore=False)
    service.seed(run_demo=False, background_vendors=40)
    return service


def test_intake_rejects_empty_submission(svc):
    from hm_core.errors import ValidationFailedError

    with pytest.raises(ValidationFailedError):
        svc.intake(IntakeRequest(body_text="   ", source="upload"))


def test_intake_json_body_creates_card_and_document_row(svc):
    att = Attachment(
        filename="inv.csv",
        content_type="text/csv",
        data_b64=base64.b64encode(
            make_csv([["field", "value"]] + [ln.split(": ", 1) for ln in INVOICE_LINES])
        ).decode(),
    )
    run = svc.intake(
        IntakeRequest(attachments=[att], source="upload", delivery_confirmed=True, po_number="PO-1")
    )
    card = run.card_list()[0]
    assert card.invoice.invoice_number == "PPS-5001" and card.invoice.amount_cents == 118_000
    assert card.invoice.vendor_id == "v-prairie"
    assert card.status in (CardStatus.PAID, CardStatus.READY)
    assert svc.store.counts()["documents"] == 1
    view = svc.payment(card.id)
    assert view["source"] == "upload" and view["amount_origin"]


def test_sample_invoices_land_in_expected_lanes(svc):
    """The six demo invoices as .eml / PDF / XLSX / PNG / CSV through the real intake path."""
    ocr = extract.ocr_backend()
    now = datetime(2026, 10, 10, 15, 0, tzinfo=UTC)
    for sample in build_samples(now):
        needs_ocr = any(name.endswith(".png") for name in sample.files) and not any(
            name.endswith((".pdf", ".xlsx", ".csv")) for name in sample.files
        )
        if needs_ocr and ocr == "none":
            pytest.skip("no OCR engine installed")
        run = svc.intake(sample.request, label=sample.key)
        card = run.card_list()[0]
        view = svc.payment(card.id)
        assert card.policy and card.policy.lane == sample.expected_lane, (sample.key, card.policy)
        assert view["status"] == sample.expected_status, sample.key
        assert view["risk"] == sample.expected_risk, sample.key
        assert view["source"] == sample.request.source
        if sample.expected_lane == Lane.HOLD:
            assert card.status == CardStatus.HOLD and view["lifecycle"] == "pending"
            assert view["checklist"], "held cards tell the owner what to do next"
    assert svc.store.counts()["documents"] == 6
