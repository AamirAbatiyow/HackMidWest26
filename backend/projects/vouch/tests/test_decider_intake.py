"""Decider wiring through the real intake path (VouchService -> VouchEngine.intake): the classification is
recorded on the card and the audit timeline, surfaced in the payment view with the engine that decided,
a kickback is a hold (never a denial) with an owner-gated draft, and the Decider can never change an
amount, a lane or a score. Uses the fake client only."""

from __future__ import annotations

import base64
import io

import pytest
from fastapi.testclient import TestClient

from vouch import main
from vouch.audit import AuditStore
from vouch.contracts import Attachment, IntakeRequest
from vouch.decider import (
    FORMAT_CRITERIA,
    TOOLS_FOR_FORMAT,
    DeciderUnavailable,
    FakeDeciderClient,
    choice_answer,
)
from vouch.demo.samples import make_pdf
from vouch.domain import CardStatus, Lane, Resolution
from vouch.engine import Submission
from vouch.policy import R_KICKBACK, R_LLM_AMOUNT
from vouch.service import VouchService

FORMATS = list(FORMAT_CRITERIA)
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


def _answers(fmt: str, conf: float, tool: str | None = None, tool_conf: float = 0.9) -> dict:
    out = {"format": choice_answer(fmt, conf, FORMATS)}
    if tool:
        out["tool"] = choice_answer(tool, tool_conf, list(TOOLS_FOR_FORMAT[fmt]))
    return out


def _blank_png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (600, 400), "white").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def make(settings, service_factory, tmp_path):
    def build(decider: FakeDeciderClient | None) -> VouchService:
        engine = service_factory(decider=decider)
        s = settings.model_copy(update={"data_dir": tmp_path, "seed_demo": False})
        svc = VouchService(s, engine=engine, store=AuditStore("sqlite://"), seed_demo=False, restore=False)
        main.set_service(svc)
        return svc

    return build


def test_decider_classification_lands_on_the_card_the_view_and_the_audit_trail(make):
    fake = FakeDeciderClient(_answers("pdf", 0.93, "pdf_text", 0.9), latency_ms=1500.0)
    svc = make(fake)
    run = svc.intake_files([("inv.pdf", "application/pdf", make_pdf(INVOICE_LINES, "Invoice"))])
    card = run.card_list()[0]
    assert card.intake is not None and card.intake.engine == "decider"
    assert (card.intake.format, card.intake.tool) == ("pdf", "pdf_text")
    assert card.intake.agrees_with_deterministic and card.intake.agrees_with_extractor
    assert len(fake.calls) == 2 and fake.max_active == 1
    # the money is untouched: parsed by the kernel from the document, not by any model
    assert card.invoice.amount_cents == 118_000 and card.invoice.amount_origin == "source"
    assert card.invoice.vendor_id == "v-prairie" and card.status in (CardStatus.READY, CardStatus.PAID)
    view = svc.payment(card.id)
    assert view["intake"]["engine"] == "decider" and view["intake"]["format_confidence"] == 0.93
    assert view["intake"]["kickback"] is False and view["intake"]["decider_calls"] == 2
    assert any(t["title"].startswith("Intake routed by decider: pdf → pdf_text") for t in view["timeline"])
    events = [e for e in card.timeline if e["event"] == "intake_classified"]
    assert events and events[0]["engine"] == "decider" and events[0]["confidence"] == 0.93
    assert any(e["type"] == "intake_classified" and e["engine"] == "decider" for e in run.events)
    # persisted with the run: the audit store sees the same classification after a reload
    saved = svc.store.load_runs()
    card_rows = [c for data in saved for c in data["cards"] if c.id == card.id]
    assert card_rows and card_rows[0].intake.engine == "decider"
    # the Decider never feeds the model: LIME factors and scores come from the scorer alone
    assert all("decider" not in str(f.get("label", "")).lower() for f in view["evidence"])
    assert card.scores is not None and card.scores.scorer == "heuristic-fallback"


def test_unreachable_decider_is_logged_and_the_run_still_completes(make):
    fake = FakeDeciderClient(fail=DeciderUnavailable("connect: refused"))
    svc = make(fake)
    run = svc.intake_files([("inv.pdf", "application/pdf", make_pdf(INVOICE_LINES, "Invoice"))])
    card = run.card_list()[0]
    assert card.intake.engine == "deterministic" and "decider unreachable" in card.intake.fallback_reason
    assert card.invoice.amount_cents == 118_000 and card.status in (CardStatus.READY, CardStatus.PAID)
    view = svc.payment(card.id)
    assert view["intake"]["engine"] == "deterministic"
    assert any("fallback: decider unreachable" in (t["detail"] or "") for t in view["timeline"])
    # the breaker is open: the next intake does not even try
    run2 = svc.intake_files([("inv2.pdf", "application/pdf", make_pdf(INVOICE_LINES, "Invoice"))])
    assert "cooling down" in run2.card_list()[0].intake.fallback_reason and len(fake.calls) == 1
    assert svc.engine.classifier.snapshot()["deterministic"] == 2


def test_disabled_decider_means_deterministic_routing_and_no_model_calls(make):
    svc = make(None)
    assert not svc.engine.classifier.enabled
    run = svc.intake_files([("inv.pdf", "application/pdf", make_pdf(INVOICE_LINES, "Invoice"))])
    card = run.card_list()[0]
    assert card.intake.engine == "deterministic" and card.intake.decider_calls == 0
    assert svc.engine.llm.stats.calls == 0
    # structured JSON submissions have nothing to route: no classification at all
    run = svc.submit([Submission(vendor_id="v-prairie", invoice_number="PPS-77", amount="640.00")])
    assert run.card_list()[0].intake is None


def test_kickback_is_a_hold_with_an_owner_gated_draft_not_a_denial(make):
    fake = FakeDeciderClient(_answers("kickback", 0.97))
    svc = make(fake)
    run = svc.intake(
        IntakeRequest(
            source="email",
            headers={"From": "Prairie AR <ar@prairiepackaging.com>", "Subject": "Invoice PPS-5002"},
            body_text="",
            attachments=[
                Attachment(
                    filename="scan.png",
                    content_type="image/png",
                    data_b64=base64.b64encode(_blank_png()).decode(),
                )
            ],
        )
    )
    card = run.card_list()[0]
    cls = card.intake
    assert cls.kickback is True and cls.engine == "decider" and cls.decider_calls == 1
    assert cls.deterministic_format == "kickback" and "OCR found no text" in cls.kickback_reason
    assert (
        cls.kickback_draft.status == "awaiting_owner" and cls.kickback_draft.to == "ar@prairiepackaging.com"
    )
    assert "$" not in cls.kickback_draft.body
    # hold, not denial: the card waits for the owner with concrete next steps
    assert card.status == CardStatus.HOLD and card.policy.lane == Lane.HOLD
    assert R_KICKBACK in card.policy.reasons and R_LLM_AMOUNT in card.policy.reasons
    assert any("kickback email" in a for a in card.policy.required_actions)
    view = svc.payment(card.id)
    assert view["status"] == "quick_check" and view["lifecycle"] == "pending"
    assert view["intake"]["kickback_draft"]["status"] == "awaiting_owner"
    assert any(e["event"] == "kickback_drafted" for e in card.timeline)
    # nothing moved and nothing can: an approve attempt is refused by policy at settle time
    assert not [c for c in run.card_list() if c.status == CardStatus.PAID]


def test_decider_friction_on_a_readable_invoice_holds_but_keeps_the_kernel_amount(make):
    fake = FakeDeciderClient(_answers("kickback", 0.97))
    svc = make(fake)
    run = svc.intake_files([("inv.pdf", "application/pdf", make_pdf(INVOICE_LINES, "Invoice"))])
    card = run.card_list()[0]
    assert card.intake.kickback and card.intake.deterministic_format == "pdf"
    assert card.invoice.amount_cents == 118_000 and card.invoice.amount_origin == "source"
    assert card.status == CardStatus.HOLD and card.policy.reasons == [R_KICKBACK]
    # the owner resolves it with a note (same path as every other hold) and the card is released
    svc.engine.resolve(card.id, Resolution(kind="resolve_risk", actor="owner", note="original re-keyed"))
    assert card.policy.lane != Lane.HOLD and card.status == CardStatus.READY


def test_health_shows_the_decider_role_and_api_exposes_the_engine(make):
    fake = FakeDeciderClient(_answers("pdf", 0.9, "pdf_text", 0.9))
    svc = make(fake)
    svc.intake_files([("inv.pdf", "application/pdf", make_pdf(INVOICE_LINES, "Invoice"))])
    with TestClient(main.app) as client:
        health = client.get("/health?format=json").json()
        assert health["decider"]["state"] == "live" and "fake-decider-2B" in health["decider"]["detail"]
        assert "decider 1" in health["decider"]["detail"]
        payments = client.get("/v1/payments").json()
        items = payments["items"] if isinstance(payments, dict) and "items" in payments else payments
        assert any((p.get("intake") or {}).get("engine") == "decider" for p in items)
    fake.fail = DeciderUnavailable("down")
    svc = make(fake)
    with TestClient(main.app) as client:
        health = client.get("/health?format=json").json()
        assert health["decider"]["state"] == "error" and "hackathon-chat" in health["decider"]["detail"]
    svc = make(None)
    with TestClient(main.app) as client:
        health = client.get("/health?format=json").json()
        assert health["decider"]["state"] == "off" and "DECIDER_ENABLED=false" in health["decider"]["detail"]
