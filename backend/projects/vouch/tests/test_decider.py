"""Strands Decider core: strict Pydantic wire models, the HTTP client (mocked transport), the fake client,
the two-step choice classifier with its fallback chain (decider -> hackathon-chat -> deterministic), the
kickback hold, and the grounding Intervention. No model is downloaded: CI only ever sees the fake client."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from pydantic import ValidationError

from vouch.agents import INTAKE_PROMPT, IntakeExtraction
from vouch.contracts import EmailEnvelope
from vouch.decider import (
    FORMAT_CRITERIA,
    TOOLS_FOR_FORMAT,
    DeciderRejected,
    DeciderUnavailable,
    DocumentProbe,
    FakeDeciderClient,
    FormatDecision,
    GroundingIntervention,
    HttpDeciderClient,
    IntakeClassifier,
    ToolDecision,
    choice,
    choice_answer,
    deterministic_route,
    parse_response,
    probes_from_submission,
    render_state,
    ungrounded_fields,
)
from vouch.llm import LLMRuntime

FORMATS = list(FORMAT_CRITERIA)
PDF_TOOLS = list(TOOLS_FOR_FORMAT["pdf"])


def _answers(fmt: str, fmt_conf: float, tool: str | None = None, tool_conf: float = 0.9) -> dict:
    out = {"format": choice_answer(fmt, fmt_conf, FORMATS)}
    if tool is not None:
        out["tool"] = choice_answer(tool, tool_conf, list(TOOLS_FOR_FORMAT[fmt]))
    return out


def _pdf_probe(chars: int = 900) -> DocumentProbe:
    return DocumentProbe(
        filename="inv.pdf",
        content_type="application/pdf",
        size=20_000,
        sniffed_kind="pdf",
        text_chars=chars,
        pages=1,
        excerpt="Invoice No: PPS-2207 Total Due: $1,180.00" if chars else "",
        warnings=[] if chars else ["no text layer found (scanned PDF?)"],
    )


def _image_probe(chars: int | None = 0) -> DocumentProbe:
    return DocumentProbe(filename="scan.png", sniffed_kind="image", text_chars=chars, size=5_000)


def _body_probe(
    text: str = "Please find attached invoice PPS-2207, total due $1,180.00 by Oct 30.",
) -> DocumentProbe:
    return DocumentProbe(filename="email-body", sniffed_kind="email_body", text_chars=len(text), excerpt=text)


ENVELOPE = EmailEnvelope(
    from_addr="ar@prairiepackaging.com", from_name="Prairie AR", subject="Invoice PPS-2207"
)


def classifier(**kw) -> IntakeClassifier:
    kw.setdefault("ocr_available", False)
    return IntakeClassifier(**kw)


# ----------------------------------------------------------------------------- wire models ----


def test_response_parses_the_verified_wire_shape():
    payload = {
        "model": "strands-decider-2B-qwen3.5-v1-2610",
        "answers": {
            "format": {
                "type": "choice",
                "choice": "pdf",
                "probabilities": {"pdf": 0.9, "image": 0.1},
                "confidence": 0.8,
            },
            "ok": {"type": "noul", "noul": 0.25},
            "sev": {
                "type": "score",
                "score": 1.0,
                "legend": {"0": "low", "1": "high"},
                "probabilities": {"0": 0.4, "1": 0.6},
                "confidence": 0.2,
            },
        },
        "usage": {"input_tokens": 86, "output_tokens": 1},
        "latency_ms": 489.01,
    }
    r = parse_response(payload)
    assert r.answers["format"].choice == "pdf" and r.answers["format"].confidence == 0.8
    assert r.answers["ok"].noul == 0.25 and r.answers["sev"].score == 1.0
    assert r.usage.input_tokens == 86 and r.latency_ms == 489.01


@pytest.mark.parametrize(
    "bad",
    [
        {
            "model": "m",
            "answers": {"f": {"type": "choice", "choice": "pdf", "probabilities": {}, "confidence": 1.5}},
        },
        {
            "model": "m",
            "answers": {"f": {"type": "choice", "choice": "pdf", "probabilities": {}, "confidence": -0.1}},
        },
        {
            "model": "m",
            "answers": {
                "f": {"type": "choice", "choice": "pdf", "probabilities": {}, "confidence": 0.5, "x": 1}
            },
        },
        {"model": "m", "answers": {"f": {"type": "verdict", "choice": "fraud"}}},
        {"model": "m", "answers": {"f": {"type": "choice", "choice": "pdf"}}},
        {"model": "m", "answers": {"f": "pdf"}},
        {"answers": {}},
        {"model": "m", "answers": {}, "surprise": True},
        "not even json",
        None,
    ],
)
def test_strict_models_reject_anything_off_shape(bad):
    with pytest.raises(DeciderRejected):
        parse_response(bad)


def test_decision_models_are_literal_and_closed():
    assert FormatDecision(format="pdf", confidence=0.7).format == "pdf"
    with pytest.raises(ValidationError):
        FormatDecision(format="fraudulent", confidence=0.7)
    with pytest.raises(ValidationError):
        FormatDecision(format="pdf", confidence=1.2)
    with pytest.raises(ValidationError):
        FormatDecision(format="pdf", confidence=0.7, amount="$1,180.00")
    with pytest.raises(ValidationError):
        ToolDecision(tool="approve_payment", confidence=0.9)


def test_choice_question_needs_two_options():
    with pytest.raises(ValueError):
        choice("pick", {"only": "one"})
    q = choice("pick", {"a": "A", "b": "B"})
    assert q == {"type": "choice", "instructions": "pick", "criteria": {"a": "A", "b": "B"}}


def test_choice_answer_helper_is_consistent():
    a = choice_answer("pdf", 0.8, FORMATS)
    assert a["choice"] == "pdf" and a["confidence"] == 0.8
    assert abs(sum(a["probabilities"].values()) - 1.0) < 1e-9
    assert a["probabilities"]["pdf"] == max(a["probabilities"].values())


# ----------------------------------------------------------------------------- http client ----


def _mock_client(handler, **kw) -> HttpDeciderClient:
    return HttpDeciderClient(
        "http://decider.test:8099", timeout_s=2.0, transport=httpx.MockTransport(handler), **kw
    )


def test_http_client_posts_the_systemone_body_and_parses_strictly():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "strands-decider-2B-qwen3.5-v1-2610",
                "answers": {"format": choice_answer("pdf", 0.9, FORMATS)},
                "usage": {"input_tokens": 120, "output_tokens": 1},
                "latency_ms": 1600.0,
            },
        )

    c = _mock_client(handler)
    r = c.ask("INVOICE SUBMISSION", {"format": choice("which format?", FORMAT_CRITERIA)})
    assert seen["path"] == "/v1/systemone"
    assert seen["body"]["state"] == "INVOICE SUBMISSION"
    assert seen["body"]["model"].startswith("StrandsAgents/")
    assert seen["body"]["questions"]["format"]["type"] == "choice"
    assert set(seen["body"]["questions"]["format"]["criteria"]) == set(FORMATS)
    assert r.answers["format"].choice == "pdf"
    assert c.calls == 1 and c.input_tokens == 120 and c.last_latency_ms == 1600.0


@pytest.mark.parametrize(
    ("response", "exc"),
    [
        (lambda req: httpx.Response(422, json={"detail": "too many options"}), DeciderRejected),
        (lambda req: httpx.Response(200, content=b"<html>not json</html>"), DeciderRejected),
        (
            lambda req: httpx.Response(200, json={"model": "m", "answers": {"format": {"type": "choice"}}}),
            DeciderRejected,
        ),
        (lambda req: httpx.Response(500, text="boom"), DeciderUnavailable),
        (lambda req: httpx.Response(503, text="loading model"), DeciderUnavailable),
    ],
)
def test_http_client_maps_errors_to_rejected_or_unavailable(response, exc):
    c = _mock_client(response)
    with pytest.raises(exc):
        c.ask("state", {"format": choice("q", FORMAT_CRITERIA)})
    assert c.calls == 0


def test_http_client_timeout_and_connect_errors_are_unavailable():
    def timeout(req):
        raise httpx.ReadTimeout("slow", request=req)

    def refused(req):
        raise httpx.ConnectError("connection refused", request=req)

    with pytest.raises(DeciderUnavailable, match="timed out"):
        _mock_client(timeout).ask("s", {"format": choice("q", FORMAT_CRITERIA)})
    with pytest.raises(DeciderUnavailable, match="strands-decider serve"):
        _mock_client(refused).ask("s", {"format": choice("q", FORMAT_CRITERIA)})


def test_http_client_health():
    ok = _mock_client(lambda req: httpx.Response(200, json={"status": "ok", "model": "d2b", "device": "cpu"}))
    assert ok.health()["device"] == "cpu"
    down = _mock_client(lambda req: httpx.Response(502))
    with pytest.raises(DeciderUnavailable):
        down.health()


# ----------------------------------------------------------------------------- fake client ----


def test_fake_client_defaults_to_first_option_at_zero_confidence_and_validates_scripts():
    fake = FakeDeciderClient()
    r = fake.ask("s", {"format": choice("q", FORMAT_CRITERIA)})
    assert r.answers["format"].choice == FORMATS[0] and r.answers["format"].confidence == 0.0
    bad = FakeDeciderClient(
        {"format": {"type": "choice", "choice": "pdf", "probabilities": {}, "confidence": 7}}
    )
    with pytest.raises(DeciderRejected):
        bad.ask("s", {"format": choice("q", FORMAT_CRITERIA)})
    assert len(bad.calls) == 1


# ------------------------------------------------------------------------------- classifier ----


def test_decider_routes_a_pdf_in_two_sequential_calls():
    fake = FakeDeciderClient(_answers("pdf", 0.92, "pdf_text", 0.88), latency_ms=1600.0)
    cls = classifier(client=fake).classify(
        [_pdf_probe()], ENVELOPE, source="email", extractor_used="pypdf+pdfplumber"
    )
    assert cls.engine == "decider" and cls.format == "pdf" and cls.tool == "pdf_text"
    assert cls.format_confidence == 0.92 and cls.tool_confidence == 0.88
    assert (
        cls.decider_calls == 2 and cls.decider_latency_ms == 3200.0 and cls.decider_model == "fake-decider-2B"
    )
    assert cls.kickback is False and cls.fallback_reason is None
    assert cls.agrees_with_deterministic is True and cls.agrees_with_extractor is True
    assert fake.max_active == 1
    # the second question only offers the tools that exist for the chosen format
    assert list(fake.calls[1]["questions"]["tool"]["criteria"]) == PDF_TOOLS
    assert "ar@prairiepackaging.com" in fake.calls[0]["state"] and "PPS-2207" in fake.calls[0]["state"]
    assert cls.summary.startswith("decider: pdf -> pdf_text")


def test_single_tool_formats_skip_the_second_question():
    fake = FakeDeciderClient(_answers("excel", 0.8))
    probe = DocumentProbe(filename="inv.xlsx", sniffed_kind="xlsx", text_chars=300)
    cls = classifier(client=fake).classify([probe], None, source="upload", extractor_used="openpyxl")
    assert cls.engine == "decider" and (cls.format, cls.tool) == ("excel", "xlsx_cells")
    assert cls.decider_calls == 1 and cls.tool_confidence == 0.8


def test_low_confidence_falls_back_to_hackathon_chat_structured_output():
    fake = FakeDeciderClient(_answers("pdf", 0.35, "pdf_text", 0.9))
    llm = LLMRuntime.scripted(
        {"classify": [{"tool": "LlmIntakeRouting", "input": {"format": "pdf", "tool": "pdf_tables"}}]}
    )
    cls = classifier(client=fake, llm=llm, threshold=0.6).classify([_pdf_probe()], ENVELOPE)
    assert cls.engine == "hackathon-chat" and cls.tool == "pdf_tables"
    assert cls.format_confidence is None and cls.tool_confidence is None  # no calibrated confidence
    assert cls.fallback_reason and "confidence 0.35 < 0.60" in cls.fallback_reason
    assert cls.decider_calls == 1  # the tool question is never asked after a weak format answer
    assert cls.agrees_with_deterministic is False and "deterministic route was pdf -> pdf_text" in cls.notes
    assert llm.stats.by_role["classify"]["calls"] == 1


def test_low_tool_confidence_also_falls_back():
    fake = FakeDeciderClient(_answers("pdf", 0.9, "pdf_ocr", 0.2))
    cls = classifier(client=fake).classify([_pdf_probe()], ENVELOPE)
    assert cls.engine == "deterministic" and cls.decider_calls == 2
    assert "tool confidence 0.20" in (cls.fallback_reason or "")


def test_threshold_is_configurable():
    fake = FakeDeciderClient(_answers("pdf", 0.35, "pdf_text", 0.4))
    cls = classifier(client=fake, threshold=0.3).classify([_pdf_probe()], ENVELOPE)
    assert cls.engine == "decider" and cls.threshold == 0.3


def test_without_an_llm_the_fallback_is_deterministic_and_says_so():
    fake = FakeDeciderClient(_answers("pdf", 0.1))
    offline = LLMRuntime("offline")
    cls = classifier(client=fake, llm=offline).classify([_pdf_probe()], ENVELOPE)
    assert cls.engine == "deterministic" and (cls.format, cls.tool) == ("pdf", "pdf_text")
    assert cls.format_confidence == 1.0 and cls.agrees_with_deterministic is True
    assert any("LLM offline" in n for n in cls.notes)


def test_unreachable_decider_falls_back_and_cools_down():
    fake = FakeDeciderClient(fail=DeciderUnavailable("connection refused"))
    c = classifier(client=fake, cooldown_s=60.0)
    first = c.classify([_pdf_probe()], ENVELOPE)
    assert first.engine == "deterministic" and "decider unreachable" in first.fallback_reason
    assert first.decider_calls == 1 and c.cooling_down and c.last_error == "connection refused"
    second = c.classify([_pdf_probe()], ENVELOPE)
    assert "cooling down" in second.fallback_reason and second.decider_calls == 0
    assert len(fake.calls) == 1, "no call is made while the breaker is open"
    assert c.stats["deterministic"] == 2 and c.stats["classified"] == 2
    c._down_until = 0.0  # breaker closes
    fake.fail = None
    fake.answers = _answers("pdf", 0.9, "pdf_text", 0.9)
    third = c.classify([_pdf_probe()], ENVELOPE)
    assert third.engine == "decider" and c.last_error is None


def test_rejected_answers_fall_back_without_a_cooldown():
    out_of_menu = FakeDeciderClient(
        {"format": choice_answer("word_document", 0.9, [*FORMATS, "word_document"])}
    )
    c = classifier(client=out_of_menu)
    cls = c.classify([_pdf_probe()], ENVELOPE)
    assert cls.engine == "deterministic" and "not one of the offered options" in cls.fallback_reason
    assert not c.cooling_down
    malformed = FakeDeciderClient(
        {"format": {"type": "choice", "choice": "pdf", "probabilities": {}, "confidence": 2}}
    )
    cls = classifier(client=malformed).classify([_pdf_probe()], ENVELOPE)
    assert cls.engine == "deterministic" and "rejected" in cls.fallback_reason
    wrong_type = FakeDeciderClient({"format": {"type": "noul", "noul": 0.9}})
    cls = classifier(client=wrong_type).classify([_pdf_probe()], ENVELOPE)
    assert cls.engine == "deterministic" and "non-choice" in cls.fallback_reason


def test_tool_outside_the_format_menu_is_rejected():
    fake = FakeDeciderClient(
        {
            "format": choice_answer("pdf", 0.9, FORMATS),
            "tool": choice_answer("image_ocr", 0.9, [*PDF_TOOLS, "image_ocr"]),
        }
    )
    cls = classifier(client=fake).classify([_pdf_probe()], ENVELOPE)
    assert cls.engine == "deterministic" and "not one of the offered options" in cls.fallback_reason


def test_hackathon_chat_inconsistent_tool_is_ignored():
    fake = FakeDeciderClient(_answers("pdf", 0.1))
    llm = LLMRuntime.scripted(
        {"classify": [{"tool": "LlmIntakeRouting", "input": {"format": "pdf", "tool": "xlsx_cells"}}]}
    )
    cls = classifier(client=fake, llm=llm).classify([_pdf_probe()], ENVELOPE)
    assert cls.engine == "deterministic" and any("inconsistent tool" in n for n in cls.notes)


def test_disabled_classifier_never_calls_a_model():
    llm = LLMRuntime.scripted(
        {"classify": [{"tool": "LlmIntakeRouting", "input": {"format": "pdf", "tool": "pdf_text"}}]}
    )
    c = classifier(client=None, llm=llm)
    cls = c.classify([_pdf_probe()], ENVELOPE)
    assert not c.enabled and cls.engine == "deterministic" and cls.decider_calls == 0
    assert llm.stats.calls == 0


def test_from_settings_honours_decider_enabled_and_url(settings):
    off = IntakeClassifier.from_settings(settings)
    assert off.client is None and off.threshold == settings.decider_min_confidence
    on = IntakeClassifier.from_settings(
        settings.model_copy(
            update={
                "decider_enabled": True,
                "decider_url": "http://10.0.2.20:8099/",
                "decider_min_confidence": 0.75,
            }
        )
    )
    assert isinstance(on.client, HttpDeciderClient) and on.client.url == "http://10.0.2.20:8099"
    assert on.threshold == 0.75 and on.client.timeout_s == settings.decider_timeout_s


def test_classifier_serialises_concurrent_invoices():
    fake = FakeDeciderClient(_answers("pdf", 0.9, "pdf_text", 0.9), sleep_s=0.01)
    c = classifier(client=fake)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: c.classify([_pdf_probe()], ENVELOPE), range(8)))
    assert all(r.engine == "decider" for r in results)
    assert fake.max_active == 1 and len(fake.calls) == 16


# --------------------------------------------------------------------------------- kickback ----


def test_unreadable_image_without_ocr_is_a_kickback_hold_with_an_owner_gated_draft():
    fake = FakeDeciderClient(_answers("kickback", 0.95))
    cls = classifier(client=fake).classify([_image_probe(0)], ENVELOPE, extractor_used="ocr:none")
    assert cls.engine == "decider" and cls.kickback is True and cls.decider_calls == 1
    assert cls.format == "kickback" and cls.tool == "none"
    assert "no OCR engine" in cls.kickback_reason
    draft = cls.kickback_draft
    assert draft is not None and draft.status == "awaiting_owner" and draft.decided_by is None
    assert draft.to == "ar@prairiepackaging.com" and draft.subject == "Re: Invoice PPS-2207"
    assert "scan.png" in draft.body and "only sent after" in draft.body
    assert "$" not in draft.body and "1,180" not in draft.body, "the template never carries amounts"
    assert cls.agrees_with_extractor is True


def test_decider_may_add_friction_but_cannot_make_unreadable_input_readable():
    # Decider says "pdf / pdf_text" with high confidence, but the file has no text and there is no OCR.
    fake = FakeDeciderClient(_answers("pdf", 0.95, "pdf_text", 0.95))
    cls = classifier(client=fake).classify([_pdf_probe(chars=0)], ENVELOPE)
    assert cls.engine == "decider" and cls.kickback is True
    assert cls.deterministic_format == "kickback" and "scanned PDF" in cls.kickback_reason
    # ... and the reverse: a readable PDF the Decider wants kicked back is held for the owner (friction only).
    fake = FakeDeciderClient(_answers("kickback", 0.95))
    cls = classifier(client=fake).classify([_pdf_probe()], ENVELOPE)
    assert cls.kickback is True and cls.deterministic_format == "pdf"
    assert "decider classified" in cls.kickback_reason and cls.agrees_with_deterministic is False


def test_readable_body_rescues_an_unreadable_attachment():
    fmt, tool, reason = deterministic_route([_body_probe(), _pdf_probe(chars=0)], ocr_available=False)
    assert (fmt, tool, reason) == ("eml_body", "email_body", None)
    fmt, tool, reason = deterministic_route([_body_probe("thanks"), _pdf_probe(chars=0)], ocr_available=False)
    assert fmt == "kickback" and "scanned PDF" in reason
    fmt, tool, _ = deterministic_route([_pdf_probe(chars=0)], ocr_available=True)
    assert (fmt, tool) == ("pdf", "pdf_ocr")
    fmt, tool, reason = deterministic_route([], ocr_available=True)
    assert fmt == "kickback" and "empty submission" in reason


def test_kickback_draft_without_envelope_asks_for_manual_forwarding():
    cls = classifier().classify([_image_probe(0)], None, source="upload")
    assert cls.kickback and cls.kickback_draft.to.startswith("(sender unknown")
    assert cls.kickback_draft.subject == "Your invoice could not be read"


# ------------------------------------------------------------------------------- probes/state ----


def test_probes_from_submission_split_the_combined_text_by_document():
    text = (
        "[[ email_body: email-body ]]\nPlease pay the attached invoice.\n\n"
        "[[ pdf: inv.pdf ]]\nInvoice No: PPS-2207\nTotal Due: $1,180.00\n\n"
        "[[ table: inv.pdf#page1 ]]\nqty | price\n\n"
        "[[ image: logo.png ]]\n"
    )
    docs = [
        {"filename": "email-body", "kind": "email_body", "extractor": "email-body"},
        {"filename": "inv.pdf", "kind": "pdf", "extractor": "pypdf+pdfplumber", "warnings": []},
        {
            "filename": "logo.png",
            "kind": "image",
            "extractor": "ocr:none",
            "warnings": ["no OCR engine installed"],
        },
    ]
    probes = probes_from_submission(docs, text)
    by_name = {p.filename: p for p in probes}
    assert by_name["email-body"].sniffed_kind == "email_body" and by_name["email-body"].text_chars > 20
    assert "PPS-2207" in by_name["inv.pdf"].excerpt and by_name["inv.pdf"].text_chars > 40
    assert by_name["logo.png"].text_chars == 0 and by_name["logo.png"].warnings
    state = render_state(probes, ENVELOPE, "email")
    assert state.startswith("INVOICE SUBMISSION (email)")
    assert "from: ar@prairiepackaging.com (Prairie AR)" in state and "attachments (2):" in state
    assert "text: none" in state and "warnings: no OCR engine installed" in state
    # a bare text submission becomes a single text probe
    assert probes_from_submission([], "Invoice INV-1 total 10.00")[0].sniffed_kind == "text"


# --------------------------------------------------------------------------------- intervention ----

SOURCE = "From: Prairie Packaging\nInvoice No: PPS-2207\nTotal Due: $1,180.00\nDue Date: 2026-10-30\n"


class _Event:
    def __init__(self, name: str, arguments: dict):
        self.tool_use = {"name": name, "toolUseId": "t1", "input": arguments}


def test_ungrounded_fields_are_found_verbatim_whitespace_and_case_insensitive():
    args = {
        "amount_quote": "$1,180.00",
        "invoice_number": "pps-2207",
        "due_date_quote": "Oct 30, 2026",
        "po_number": None,
    }
    assert ungrounded_fields(args, SOURCE) == [("due_date_quote", "Oct 30, 2026")]
    assert ungrounded_fields({"vendor_name": "prairie   PACKAGING"}, SOURCE) == []  # whitespace runs + case
    assert ungrounded_fields({"amount_quote": "$ 1,180.00"}, SOURCE) == [
        ("amount_quote", "$ 1,180.00")
    ]  # reformatted


def test_grounding_intervention_guides_then_proceeds():
    gate = GroundingIntervention(SOURCE, max_guides=2)
    bad = {
        "vendor_name": "Prairie Packaging",
        "invoice_number": "PPS-2207",
        "amount_quote": "$11,800.00",
        "due_date_quote": "2026-10-30",
    }
    v1 = gate.before_tool_call(_Event("IntakeExtraction", bad))
    assert type(v1).__name__ == "Guide" and "amount_quote='$11,800.00'" in v1.feedback and gate.guides == 1
    v2 = gate.before_tool_call(_Event("IntakeExtraction", bad))
    assert type(v2).__name__ == "Guide" and gate.guides == 2
    v3 = gate.before_tool_call(_Event("IntakeExtraction", bad))  # budget spent: the kernel's check takes over
    assert type(v3).__name__ == "Proceed" and gate.guides == 2
    assert [e["verdict"] for e in gate.log] == ["guided", "guided", "proceeded"]
    good = {**bad, "amount_quote": "$1,180.00"}
    assert (
        type(GroundingIntervention(SOURCE).before_tool_call(_Event("IntakeExtraction", good))).__name__
        == "Proceed"
    )
    # other tools are none of the gate's business
    assert type(gate.before_tool_call(_Event("vendor_lookup", {"amount_quote": "$9"}))).__name__ == "Proceed"


def test_grounding_intervention_runs_inside_a_strands_agent():
    """A scripted intake agent first invents an amount; the Guide sends it back and the corrected call wins."""
    invented = {
        "vendor_name": "Prairie Packaging",
        "invoice_number": "PPS-2207",
        "amount_quote": "$11,800.00",
        "due_date_quote": "2026-10-30",
    }
    corrected = {**invented, "amount_quote": "$1,180.00"}
    llm = LLMRuntime.scripted(
        {
            "intake": [
                {"tool": "IntakeExtraction", "input": invented},
                {"tool": "IntakeExtraction", "input": corrected},
            ]
        }
    )
    gate = GroundingIntervention(SOURCE)
    out = llm.structured(
        "intake", INTAKE_PROMPT, f"INVOICE TEXT:\n{SOURCE}", IntakeExtraction, interventions=[gate]
    )
    assert isinstance(out, IntakeExtraction) and out.amount_quote == "$1,180.00"
    assert gate.guided and gate.guides == 1 and llm.stats.model_calls == 2


def test_grounding_intervention_never_blocks_a_stubborn_model():
    """The red-team shape: the model repeats the invented amount. After the guide budget the call proceeds and
    the engine's provenance check (not the gate) decides what happens to the number."""
    invented = {
        "vendor_name": "Prairie Packaging",
        "invoice_number": "PPS-2207",
        "amount_quote": "$11,800.00",
        "due_date_quote": "2026-10-30",
    }
    llm = LLMRuntime.scripted(
        {"intake": [{"tool": "IntakeExtraction", "input": invented}]}
    )  # repeats forever
    gate = GroundingIntervention(SOURCE, max_guides=2)
    out = llm.structured(
        "intake", INTAKE_PROMPT, f"INVOICE TEXT:\n{SOURCE}", IntakeExtraction, interventions=[gate]
    )
    assert isinstance(out, IntakeExtraction) and out.amount_quote == "$11,800.00"
    assert gate.guides == 2 and llm.stats.model_calls == 3


def test_threading_lock_type_is_real():  # guards against accidentally swapping the lock for a no-op
    assert isinstance(FakeDeciderClient()._lock, type(threading.Lock()))
