"""Invoice-intake decision classifiers (advisory routing only).

Three single-choice questions, asked as a chain and only when deterministic code cannot answer:

1. FORMAT   "What format does this inbound email contain?"
            pdf_attachment | image_attachment | excel_attachment | csv_attachment | email_body_text |
            unreadable_or_unsupported
2. TOOL     "Which extraction tool should handle this?"  (fed by 1)
            pdf_text | image_ocr | excel_reader | csv_reader | body_parser | request_resubmission
3. KICKBACK "Why can this submission not be processed?"  (only when it is kicked back)
            unsupported_format | unreadable_scan | empty_submission | missing_fields | ambiguous_submission
            - the answer selects a fixed reply template; the model never writes the email.

Deterministic first. MIME type, extension, magic bytes and the text-layer probe answer the obvious cases
with zero model calls (0 ms, 0 tokens). A model is consulted only for the ambiguity triggers in
``AMBIGUITY`` (or for every submission with ``INTAKE_CLASSIFIER=always``): the Strands Decider server
when one is configured, otherwise the shared ``DecisionClassifier`` (Strands structured output over the
enum, ``max_tokens`` 48, two attempts) on hackathon-chat. Every decision - code, Decider or chat - is a
``Decision`` record (question, options, answer, accepted, engine, latency, tokens) kept on the card, in
the audit log and in the API payload.

What a model can do here: route a document to an extractor, and add friction (kick a submission back to
the sender = a HOLD plus a draft email the owner must approve). What it cannot do: pick an option the
evidence rules out (admissibility), make unreadable input readable, write or send the kickback email, or
touch amounts, lanes or scores.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from functools import partial
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model, model_validator

from hm_agents_common.classifier import (
    STRICT,
    Decision,
    Question,
    StrictDecisionModel,
    decided,
    validate_decision,
)
from vouch.contracts import EmailEnvelope, ExtractedDocument
from vouch.decider.client import (
    ChoiceAnswer,
    DeciderClient,
    DeciderRejected,
    DeciderUnavailable,
    HttpDeciderClient,
    SystemOneResponse,
    choice,
)

log = logging.getLogger(__name__)

# ------------------------------------------------------------------------------------ vocabulary ----

FORMATS = (
    "pdf_attachment",
    "image_attachment",
    "excel_attachment",
    "csv_attachment",
    "email_body_text",
    "unreadable_or_unsupported",
)
TOOLS = ("pdf_text", "image_ocr", "excel_reader", "csv_reader", "body_parser", "request_resubmission")
KICKBACK_REASONS = (
    "unsupported_format",
    "unreadable_scan",
    "empty_submission",
    "missing_fields",
    "ambiguous_submission",
)
Format = Literal[
    "pdf_attachment",
    "image_attachment",
    "excel_attachment",
    "csv_attachment",
    "email_body_text",
    "unreadable_or_unsupported",
]
Tool = Literal["pdf_text", "image_ocr", "excel_reader", "csv_reader", "body_parser", "request_resubmission"]
KickbackCode = Literal[
    "unsupported_format", "unreadable_scan", "empty_submission", "missing_fields", "ambiguous_submission"
]
Engine = Literal["deterministic", "decider", "hackathon-chat"]
Policy = Literal["auto", "always", "off"]

FORMAT_CRITERIA: dict[str, str] = {
    "pdf_attachment": "the invoice is a PDF attachment (digital with a text layer, or a scanned PDF)",
    "image_attachment": "the invoice is a photo or scan image attachment: PNG, JPEG, TIFF, WebP, BMP",
    "excel_attachment": "the invoice is an Excel workbook attachment (.xlsx / .xlsm)",
    "csv_attachment": "the invoice is a CSV table attachment",
    "email_body_text": "the invoice is plain text: written in the email body itself (or a .txt attachment)",
    "unreadable_or_unsupported": (
        "nothing usable: unsupported file types (archives, Word, HTML), empty or encrypted files, pictures "
        "without text, or a message with no invoice at all"
    ),
}
TOOL_CRITERIA: dict[str, str] = {
    "pdf_text": "PDF text-layer extraction (pypdf + pdfplumber tables) for digital PDFs",
    "image_ocr": "OCR (Tesseract / RapidOCR) for images and for scanned PDFs without a text layer",
    "excel_reader": "openpyxl cell reader for Excel workbooks",
    "csv_reader": "CSV row reader",
    "body_parser": "plain-text invoice parser over the email body (or a text attachment)",
    "request_resubmission": "no tool can read this; ask the sender to re-send it in a supported format",
}
REASON_CRITERIA: dict[str, str] = {
    "unsupported_format": "the file type is not one we accept (PDF, Excel, CSV, image, plain text)",
    "unreadable_scan": "the scan, photo or PDF contains no legible text",
    "empty_submission": "the message has no attachment and no invoice text",
    "missing_fields": "the invoice is readable but required fields are missing",
    "ambiguous_submission": "it is unclear which part of the message is the invoice",
}

TOOLS_FOR_FORMAT: dict[str, tuple[str, ...]] = {
    "pdf_attachment": ("pdf_text", "image_ocr"),
    "image_attachment": ("image_ocr",),
    "excel_attachment": ("excel_reader",),
    "csv_attachment": ("csv_reader",),
    "email_body_text": ("body_parser",),
    "unreadable_or_unsupported": ("request_resubmission",),
}
FORMAT_FOR_KIND: dict[str, str] = {
    "pdf": "pdf_attachment",
    "image": "image_attachment",
    "xlsx": "excel_attachment",
    "csv": "csv_attachment",
    "text": "email_body_text",
    "email_body": "email_body_text",
}
# Which tools the deterministic extractors actually ran (``ExtractedDocument.extractor`` values).
EXTRACTOR_TOOLS: dict[str, tuple[str, ...]] = {
    "pypdf+pdfplumber": ("pdf_text",),
    "pypdf+pdfplumber+ocr": ("image_ocr", "pdf_text"),
    "ocr:tesseract": ("image_ocr",),
    "ocr:rapidocr": ("image_ocr",),
    "ocr:none": ("request_resubmission",),
    "openpyxl": ("excel_reader",),
    "csv": ("csv_reader",),
    "email-body": ("body_parser",),
    "text": ("body_parser",),
}
# Which sniffed kinds a tool decision reads: the service applies ``extractor_for(tool)`` to attachments of
# these kinds and the default extractor to every other attachment (the chain picks the tool for the invoice,
# a terms-and-conditions PDF next to an Excel invoice is still read the ordinary way).
KINDS_FOR_TOOL: dict[str, tuple[str, ...]] = {
    "pdf_text": ("pdf",),
    "image_ocr": ("image", "pdf"),
    "excel_reader": ("xlsx",),
    "csv_reader": ("csv",),
    "body_parser": ("text", "unknown"),
    "request_resubmission": (),
}
REQUIRED_FIELDS = ("vendor_name", "invoice_number", "amount")
FIELD_LABELS = {
    "vendor_name": "the supplier name",
    "invoice_number": "the invoice number",
    "amount": "the invoice total",
    "due_date": "the due date",
}
AMBIGUITY: dict[str, str] = {
    "multiple_candidates": "several readable attachments of different kinds; unclear which one is the invoice",
    "unknown_type_with_text": "an attachment of unknown type that decodes as text",
    "body_without_invoice_markers": "no readable attachment and the email body has no invoice markers",
    "thin_text_layer": "a PDF with only a few characters of text (a stamp on a scan?)",
}

# ------------------------------------------------------------------------- strict output models ----
# One strict Pydantic model per classifier. Strands validates every structured-output call with the model
# class: ``extra="forbid"`` rejects extra fields, ``strict=True`` rejects coerced types (1, "1", True are
# not an option name), the ``Literal`` answer rejects anything outside the enum, and ``reason_code`` is an
# enum as well, so the model has no free-text channel. On a ValidationError the SDK returns the error to
# the model, which gets exactly one retry (``limits={"turns": 2}``); then the deterministic default is
# used and the submission goes to the owner (kickback or review), never to payment.

FormatBasis = Literal[
    "mime_type",  # the declared content type names the format
    "file_extension",  # the file name does
    "file_signature",  # the sniffed bytes do
    "text_layer",  # a PDF with selectable text
    "body_text",  # the invoice is written in the email body
    "no_usable_content",  # nothing readable or supported
    "unsure",
    "not_stated",  # engines that return no basis (a Decider server, deterministic code)
]
ToolBasis = Literal[
    "only_tool_for_format",
    "text_layer_present",
    "no_text_layer",
    "tabular_data",
    "plain_text",
    "nothing_readable",
    "unsure",
    "not_stated",
]
KickbackBasis = Literal[
    "file_type",
    "no_legible_text",
    "no_attachment_or_text",
    "required_fields_missing",
    "several_candidates",
    "unsure",
    "not_stated",
]
NOT_STATED = "not_stated"


class FormatDecision(StrictDecisionModel):
    """Question 1: the format of the inbound submission."""

    answer: Format = Field(description="Exactly one of the listed formats, verbatim.")
    reason_code: FormatBasis = Field(description="The evidence the choice rests on.")


class ToolDecision(StrictDecisionModel):
    """Question 2: the extraction tool for the format decided in question 1.

    ``format`` is the question-1 answer the tool is chosen for; the validator rejects pairs the extractors
    cannot honour (``csv_reader`` only for ``csv_attachment``, OCR only for images and PDFs, ...).
    ``request_resubmission`` is allowed for every format: a model may add friction, never skip a step.
    """

    format: Format = Field(description="The format decided in the previous question, verbatim.")
    answer: Tool = Field(description="Exactly one of the listed tools, verbatim.")
    reason_code: ToolBasis = Field(description="The evidence the choice rests on.")

    @model_validator(mode="after")
    def _tool_fits_format(self) -> ToolDecision:
        allowed = (*TOOLS_FOR_FORMAT[self.format], "request_resubmission")
        if self.answer not in allowed:
            raise ValueError(
                f"tool {self.answer!r} cannot handle format {self.format!r}; "
                f"allowed: {', '.join(dict.fromkeys(allowed))}"
            )
        return self

    @classmethod
    def for_format(cls, fmt: str) -> type[ToolDecision]:
        """The schema asked once the format is known: ``format`` is pinned to that value, so a model that
        silently switches formats mid-chain fails validation instead of being believed."""
        if fmt not in FORMATS:
            raise ValueError(f"unknown format {fmt!r}")
        if fmt not in _TOOL_DECISION_FOR:
            _TOOL_DECISION_FOR[fmt] = create_model(
                "ToolDecision",
                __base__=cls,
                __doc__=cls.__doc__,
                format=(Literal[fmt], Field(description=f"Must be {fmt!r}: the format decided before.")),  # type: ignore[valid-type]
            )
        return _TOOL_DECISION_FOR[fmt]


_TOOL_DECISION_FOR: dict[str, type[ToolDecision]] = {}


class KickbackDecision(StrictDecisionModel):
    """Question 3: which fixed reply template (reason code) to send back. Never the email text."""

    answer: KickbackCode = Field(description="Exactly one of the listed reason codes, verbatim.")
    reason_code: KickbackBasis = Field(description="The evidence the choice rests on.")


class IntakeDecisionChain(BaseModel):
    """The whole chain as one validated unit (used to check any engine's pair before it is adopted)."""

    model_config = STRICT

    format: FormatDecision
    tool: ToolDecision
    kickback: KickbackDecision | None = None

    @model_validator(mode="after")
    def _consistent(self) -> IntakeDecisionChain:
        if self.tool.format != self.format.answer:
            raise ValueError(
                f"tool decision was made for format {self.tool.format!r}, "
                f"but the format decision is {self.format.answer!r}"
            )
        if self.format.answer == "unreadable_or_unsupported" and self.kickback is None:
            raise ValueError("an unreadable or unsupported submission needs a kickback decision")
        return self


FORMAT_QUESTION = Question(
    "format",
    "What format does this inbound email contain?",
    FORMATS,
    FORMAT_CRITERIA,
    when_unsure="unreadable_or_unsupported",
    model=FormatDecision,
)
TOOL_QUESTION = Question(
    "tool",
    "Which extraction tool should handle this?",
    TOOLS,
    TOOL_CRITERIA,
    when_unsure="request_resubmission",
    model=ToolDecision,
)
REASON_QUESTION = Question(
    "kickback_reason",
    "Why can this submission not be processed as an invoice? The answer selects a fixed reply template.",
    KICKBACK_REASONS,
    REASON_CRITERIA,
    when_unsure="ambiguous_submission",
    model=KickbackDecision,
)


def tool_question_for(fmt: str) -> Question:
    """Question 2 with its schema pinned to the format decided in question 1."""
    return TOOL_QUESTION.with_model(ToolDecision.for_format(fmt))


DEFAULT_THRESHOLD = 0.6
DEFAULT_MAX_TOKENS = 48
DEFAULT_MAX_ATTEMPTS = 2
EXCERPT_CHARS = 300
THIN_TEXT_CHARS = 40

_INVOICE_MARKERS = re.compile(
    r"\b(invoice|inv\.?\s*(?:no|#|number)|rechnung|factura|facture|fattura|total|amount due|balance due|"
    r"due date|remit(?:tance)?|purchase order|po\s*(?:no|#|number))\b",
    re.I,
)
_MONEY = re.compile(r"(?:[$€£]\s?\d[\d,]*(?:\.\d{2})?|\b\d[\d,]*\.\d{2}\b)")
_BANKISH = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{8,}\b|\b\d{8,}\b|\b\d{2,6}(?:[ -]\d{2,6}){2,}\b")


# ------------------------------------------------------------------------------------ records ----


class DocumentProbe(BaseModel):
    """Cheap, deterministic facts about one attachment (or the email body) that the classifier reads."""

    filename: str
    content_type: str = ""
    size: int = 0
    sniffed_kind: str = "unknown"  # pdf | image | xlsx | csv | text | email_body | unknown
    text_chars: int | None = None  # None when no extraction has run yet
    tables: int = 0
    pages: int | None = None
    warnings: list[str] = Field(default_factory=list)
    extractor: str | None = None
    excerpt: str = ""


class Route(BaseModel):
    """What deterministic code concludes from the probes, and whether it is sure."""

    format: Format
    tool: Tool
    code: KickbackCode | None = None  # a deterministic kickback reason (unreadable / unsupported / empty)
    detail: str | None = None
    basis: str = ""  # the evidence the call rests on (for the audit record)
    ambiguous: list[str] = Field(default_factory=list)  # ``AMBIGUITY`` keys; empty = obvious
    admissible_formats: list[str] = Field(default_factory=list)

    @property
    def obvious(self) -> bool:
        return not self.ambiguous


class KickbackDraft(BaseModel):
    """The email that asks the sender for a usable invoice.

    Rendered from a fixed template chosen by ``code``; never contains amounts or bank details; it is a
    draft in the owner's queue (``awaiting_owner``) until the owner approves or declines it. Nothing in
    this codebase sends it: ``sent_at`` exists so a mail integration can record a send *after* approval.
    """

    to: str
    subject: str
    body: str
    code: KickbackCode
    reason: str
    missing_fields: list[str] = Field(default_factory=list)
    chosen_by: Engine = "deterministic"
    status: Literal["awaiting_owner", "approved", "declined"] = "awaiting_owner"
    decided_by: str | None = None
    decided_at: str | None = None
    note: str = ""
    sent_at: str | None = None


class IntakeClassification(BaseModel):
    engine: Engine  # who made the final format/tool call
    policy: Policy = "auto"
    format: Format
    tool: Tool
    format_confidence: float | None = None  # None: the engine has no calibrated confidence (chat model)
    tool_confidence: float | None = None
    threshold: float = DEFAULT_THRESHOLD
    ambiguous: list[str] = Field(default_factory=list)  # why a model was consulted (empty = obvious)
    decisions: list[Decision] = Field(default_factory=list)  # the chain, in order, rejected attempts included
    kickback: bool = False
    kickback_code: KickbackCode | None = None
    kickback_reason: str | None = None
    kickback_draft: KickbackDraft | None = None
    missing_fields: list[str] = Field(default_factory=list)
    # Safe default: the deterministic route was ambiguous, a model was consulted and no answer passed
    # validation / admissibility -> the card waits for the owner (R_INTAKE_REVIEW), it is never paid on a guess.
    review_required: bool = False
    review_reason: str | None = None
    validation_failures: int = 0  # structured outputs the SDK rejected across the chain (audit)
    decider_model: str | None = None
    decider_calls: int = 0
    decider_latency_ms: float | None = None
    llm_calls: int = 0
    model_latency_ms: float = 0.0  # summed over every model decision (Decider + chat)
    tokens: int = 0  # idem
    fallback_reason: str | None = None
    deterministic_format: Format
    deterministic_tool: Tool
    agrees_with_deterministic: bool | None = None
    extractor_used: str | None = None
    agrees_with_extractor: bool | None = None
    # True when the chain was decided from pre-extraction probes and chose the extractor (the live intake
    # service); ``IntakeClassifier.complete`` then adds what extraction revealed.
    before_extraction: bool = False
    notes: list[str] = Field(default_factory=list)
    at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    @property
    def model_calls(self) -> int:
        return self.decider_calls + self.llm_calls

    @property
    def summary(self) -> str:
        conf = "" if self.format_confidence is None else f" ({self.format_confidence:.2f})"
        cost = (
            f", {self.model_calls} model call(s), {self.tokens} tokens"
            if self.model_calls
            else ", 0 model calls"
        )
        return (
            f"{self.engine}: {self.format} -> {self.tool}{conf}{cost}"
            + (f" · kickback [{self.kickback_code}]" if self.kickback else "")
            + (" · owner review" if self.review_required else "")
        )


# ------------------------------------------------------------------------------------ probes ----

_HEADER = re.compile(r"^\[\[ (\w+): (.+?) \]\]$", re.M)


def _squash(text: str, limit: int = EXCERPT_CHARS) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:limit]


def probes_from_documents(docs: list[ExtractedDocument]) -> list[DocumentProbe]:
    """After extraction: probes straight from the extracted documents."""
    return [
        DocumentProbe(
            filename=d.filename,
            sniffed_kind=d.kind,
            text_chars=len(d.text or ""),
            tables=len(d.tables),
            warnings=list(d.warnings),
            extractor=d.extractor,
            excerpt=_squash(d.text),
        )
        for d in docs
    ]


def probes_from_submission(documents: list[dict[str, Any]], text: str | None) -> list[DocumentProbe]:
    """From a ``Submission``: the document metadata plus the per-document text found in the combined text
    (``[[ kind: filename ]]`` sections written by ``combine_documents``)."""
    sections: dict[str, str] = {}
    body = text or ""
    matches = list(_HEADER.finditer(body))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        if m.group(1) != "table":
            sections[m.group(2)] = body[m.end() : end]
    probes: list[DocumentProbe] = []
    for d in documents:
        name = str(d.get("filename") or "attachment")
        section = sections.get(name, "")
        probes.append(
            DocumentProbe(
                filename=name,
                sniffed_kind=str(d.get("kind") or "unknown"),
                text_chars=len(section.strip()) if sections else None,
                warnings=list(d.get("warnings") or []),
                extractor=d.get("extractor"),
                excerpt=_squash(section),
            )
        )
    if not probes and body.strip():
        probes.append(
            DocumentProbe(
                filename="text", sniffed_kind="text", text_chars=len(body.strip()), excerpt=_squash(body)
            )
        )
    return probes


def probes_from_files(files: list[tuple[str, str | None, bytes]], body_text: str = "") -> list[DocumentProbe]:
    """Before extraction: sniff the type and, for PDFs, whether a text layer exists, without running OCR."""
    from vouch.intake.extract import detect_kind

    probes: list[DocumentProbe] = []
    if body_text.strip():
        probes.append(
            DocumentProbe(
                filename="email-body",
                content_type="text/plain",
                size=len(body_text),
                sniffed_kind="email_body",
                text_chars=len(body_text.strip()),
                excerpt=_squash(body_text),
            )
        )
    for filename, ctype, data in files:
        kind = detect_kind(filename, ctype, data)
        probe = DocumentProbe(filename=filename, content_type=ctype or "", size=len(data), sniffed_kind=kind)
        if kind == "pdf":
            _probe_pdf(probe, data)
        elif kind in ("csv", "text", "unknown"):
            if kind == "unknown" and not _looks_like_text(data):
                probe.text_chars = 0  # binary junk: not text
            else:
                text = data.decode("utf-8", errors="replace")
                probe.text_chars, probe.excerpt = len(text.strip()), _squash(text)
        probes.append(probe)
    return probes


def _looks_like_text(data: bytes) -> bool:
    """Strict UTF-8 and (almost) no control bytes in the first 4 KB; anything else is binary."""
    sample = data[:4096]
    if not sample.strip():
        return False
    try:
        text = sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    control = sum(1 for ch in text if ord(ch) < 32 and ch not in "\t\n\r\f")
    return control <= 0.02 * len(text)


def _probe_pdf(probe: DocumentProbe, data: bytes) -> None:
    try:
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        probe.pages = len(reader.pages)
        text = "\n".join((p.extract_text() or "") for p in reader.pages[:2])
        probe.text_chars, probe.excerpt = len(text.strip()), _squash(text)
        if not text.strip():
            probe.warnings.append("no text layer found (scanned PDF?)")
    except Exception as exc:  # encrypted or broken PDF: the classifier sees the warning
        probe.warnings.append(f"pypdf could not open the file: {type(exc).__name__}")
        probe.text_chars = 0


# ------------------------------------------------------------------------------- deterministic ----

_KIND_PRIORITY = {"pdf": 0, "xlsx": 1, "csv": 2, "image": 3, "text": 4, "unknown": 5, "email_body": 9}


def _has_invoice_markers(text: str) -> bool:
    return bool(_INVOICE_MARKERS.search(text or "") or _MONEY.search(text or ""))


def _ocr_ran(probe: DocumentProbe) -> bool:
    """After extraction: OCR was already tried on this file (so "no text" means unreadable, not "try OCR")."""
    extractor = probe.extractor or ""
    return extractor.endswith("+ocr") or extractor.startswith("ocr:")


def deterministic_route(probes: list[DocumentProbe], ocr_available: bool) -> Route:
    """The sniffing route: what intake decides from MIME type, extension, magic bytes and text probes.

    Obvious cases come back with ``ambiguous == []``; the triggers in ``AMBIGUITY`` mark the cases a model
    may be consulted for. The route always carries a usable default, so a model is never *required*.
    """
    attachments = sorted(
        (p for p in probes if p.sniffed_kind != "email_body"),
        key=lambda p: _KIND_PRIORITY.get(p.sniffed_kind, 5),
    )
    body = next((p for p in probes if p.sniffed_kind == "email_body"), None)
    body_chars = (body.text_chars or 0) if body else 0
    body_text = body.excerpt if body else ""
    admissible = {"unreadable_or_unsupported"}
    if body_chars > 0:
        admissible.add("email_body_text")
    candidates: list[tuple[str, str, str]] = []  # (format, tool, basis)
    unreadable: list[tuple[str, str]] = []  # (code, detail)
    ambiguous: list[str] = []
    for p in attachments:
        kind, chars = p.sniffed_kind, p.text_chars
        if kind in FORMAT_FOR_KIND and kind != "text":
            admissible.add(FORMAT_FOR_KIND[kind])
        if kind == "pdf":
            if chars is None or chars > THIN_TEXT_CHARS:
                layer = "text layer present" if chars is None else f"text layer {chars} chars"
                candidates.append(("pdf_attachment", "pdf_text", f"{p.filename}: PDF, {layer}"))
            elif ocr_available and not _ocr_ran(p):
                candidates.append(("pdf_attachment", "image_ocr", f"{p.filename}: PDF without a text layer"))
                if chars:
                    ambiguous.append("thin_text_layer")
            else:
                why = "OCR found no text" if ocr_available else "no OCR engine"
                unreadable.append(
                    ("unreadable_scan", f"{p.filename}: scanned PDF without a text layer and {why}")
                )
        elif kind == "image":
            if ocr_available and (chars is None or chars > 20):
                candidates.append(("image_attachment", "image_ocr", f"{p.filename}: image, OCR available"))
            else:
                why = "no OCR engine installed" if not ocr_available else "OCR found no text"
                unreadable.append(("unreadable_scan", f"{p.filename}: {why}"))
        elif kind == "xlsx":
            candidates.append(("excel_attachment", "excel_reader", f"{p.filename}: Excel workbook"))
        elif kind == "csv":
            candidates.append(("csv_attachment", "csv_reader", f"{p.filename}: CSV table"))
        elif kind == "text":
            if chars is None or chars > 20:
                admissible.add("email_body_text")
                candidates.append(("email_body_text", "body_parser", f"{p.filename}: plain-text attachment"))
            else:
                unreadable.append(("unsupported_format", f"{p.filename}: empty text file"))
        elif chars is not None and chars > THIN_TEXT_CHARS:
            admissible.add("email_body_text")
            ambiguous.append("unknown_type_with_text")
            candidates.append(
                ("email_body_text", "body_parser", f"{p.filename}: unknown type, decodes as text")
            )
        else:
            unreadable.append(
                ("unsupported_format", f"{p.filename}: unsupported file type ({p.content_type or 'unknown'})")
            )
    if len({fmt for fmt, _, _ in candidates}) > 1:
        ambiguous.append("multiple_candidates")
    common = {"ambiguous": ambiguous, "admissible_formats": sorted(admissible)}
    if candidates:
        fmt, tool, basis = candidates[0]
        return Route(format=fmt, tool=tool, basis=basis, **common)  # type: ignore[arg-type]
    if body_chars > 0:
        if _has_invoice_markers(body_text):
            return Route(
                format="email_body_text",
                tool="body_parser",
                basis="email body with invoice markers",
                **common,
            )
        if not unreadable:
            ambiguous.append("body_without_invoice_markers")
            return Route(
                format="email_body_text",
                tool="body_parser",
                basis="email body without invoice markers (default)",
                **common,
            )
        # "please find attached" plus an unreadable attachment: the attachment was the invoice
    if unreadable:
        code, _ = unreadable[0]
        detail = "; ".join(d for _, d in unreadable[:3])
        return Route(
            format="unreadable_or_unsupported",
            tool="request_resubmission",
            code=code,  # type: ignore[arg-type]
            detail=detail,
            basis=detail,
            **common,
        )
    return Route(
        format="unreadable_or_unsupported",
        tool="request_resubmission",
        code="empty_submission",
        detail="no attachment and no text in the email body",
        basis="empty submission",
        **common,
    )


def admissible_tools(fmt: str, ocr_available: bool) -> set[str]:
    tools = set(TOOLS_FOR_FORMAT.get(fmt, ())) | {"request_resubmission"}
    if not ocr_available:
        tools.discard("image_ocr")
    return tools


def render_state(
    probes: list[DocumentProbe],
    envelope: EmailEnvelope | None,
    source: str,
    missing_fields: Iterable[str] = (),
) -> str:
    """The evidence a model reads: envelope facts, body excerpt, one line per attachment, kernel parse."""
    lines = [f"INVOICE SUBMISSION ({source})"]
    if envelope is not None:
        sender = envelope.from_addr + (f" ({envelope.from_name})" if envelope.from_name else "")
        lines.append(f"from: {sender or '(unknown)'}")
        if envelope.reply_to and envelope.reply_to != envelope.from_addr:
            lines.append(f"reply-to: {envelope.reply_to}")
        lines.append(f"subject: {envelope.subject or '(none)'}")
    body = next((p for p in probes if p.sniffed_kind == "email_body"), None)
    lines.append(f"body: {body.excerpt or '(no text)'}" if body else "body: (no email body)")
    attachments = [p for p in probes if p.sniffed_kind != "email_body"]
    lines.append(f"attachments ({len(attachments)}):" if attachments else "attachments: none")
    for i, p in enumerate(attachments, start=1):
        facts = [
            p.filename,
            p.content_type or "unknown type",
            f"{p.size} bytes" if p.size else "",
            f"sniffed: {p.sniffed_kind}",
        ]
        if p.pages is not None:
            facts.append(f"{p.pages} page(s)")
        if p.text_chars is not None:
            facts.append(f"text: {p.text_chars} chars" if p.text_chars else "text: none")
        if p.tables:
            facts.append(f"tables: {p.tables}")
        if p.warnings:
            facts.append("warnings: " + "; ".join(p.warnings[:2]))
        lines.append(f"  {i}. " + " · ".join(f for f in facts if f))
        if p.excerpt:
            lines.append(f'     excerpt: "{p.excerpt}"')
    missing = list(missing_fields)
    if missing:
        lines.append(f"kernel parse: required fields missing: {', '.join(missing)}")
    return "\n".join(lines)


# ------------------------------------------------------------------------------------ kickback ----

TEMPLATES: dict[str, tuple[str, str]] = {
    "unsupported_format": (
        "we could not read an invoice from the type of file you sent",
        "Please re-send the invoice as a PDF with selectable text, an Excel or CSV export, or a clear photo "
        "or scan (PNG or JPEG).",
    ),
    "unreadable_scan": (
        "the scan or photo you sent did not contain legible text",
        "Please re-send a clear, well-lit scan or photo of the invoice, or a PDF with selectable text.",
    ),
    "empty_submission": (
        "your message did not contain an invoice",
        "Please attach the invoice as a PDF, Excel, CSV or image file, or paste its full contents into the "
        "email.",
    ),
    "missing_fields": (
        "the invoice is missing information we need before it can be scheduled",
        "Please re-send the invoice showing {fields}.",
    ),
    "ambiguous_submission": (
        "we could not tell which part of your message is the invoice",
        "Please re-send one invoice per email, as a PDF with selectable text, an Excel or CSV export, or a "
        "clear photo.",
    ),
}
GENERIC_SUBJECT = "Your invoice could not be processed"


def _clean(text: str) -> bool:
    """True when the text carries nothing that could be an amount or an account number."""
    norm = re.sub(r"[_\-]+", " ", text)
    return not (_MONEY.search(norm) or _BANKISH.search(norm))


def render_kickback(
    code: str,
    envelope: EmailEnvelope | None,
    filenames: Iterable[str],
    *,
    reason: str,
    missing_fields: Iterable[str] = (),
    chosen_by: Engine = "deterministic",
    owner_name: str = "the owner",
    business_name: str = "Accounts Payable",
) -> KickbackDraft:
    """Deterministic template: the only variable parts are the code, the sender, file names and the
    *names* of missing fields. Subjects or file names that carry a number that could be an amount or
    an account are replaced, so nothing from the invoice can leak into the reply."""
    if code not in TEMPLATES:
        code = "ambiguous_submission"
    happened, ask = TEMPLATES[code]
    missing = [f for f in missing_fields if f in FIELD_LABELS]
    if code == "missing_fields":
        labels = [FIELD_LABELS[f] for f in missing] or ["the supplier name, invoice number and total"]
        ask = ask.format(fields=", ".join(labels[:-1]) + (" and " if len(labels) > 1 else "") + labels[-1])
    names = [n for n in filenames if _clean(n)][:4]
    attached = f" with {len(names)} attachment(s) ({', '.join(names)})" if names else ""
    greeting = (
        f"Hello {envelope.from_name},"
        if envelope and envelope.from_name and _clean(envelope.from_name)
        else "Hello,"
    )
    subject = GENERIC_SUBJECT
    if envelope and envelope.subject and _clean(envelope.subject):
        subject = f"Re: {envelope.subject}"
    body = (
        f"{greeting}\n\n"
        f"We received your message{attached}, but {happened}.\n{ask}\n\n"
        "Please send it from the email address we have on file. Do not change bank or payment details by "
        "email; call us if anything about payment instructions has changed.\n\n"
        f"This reply was prepared automatically from a fixed template and is only sent after {owner_name} "
        f"reviews it.\n{business_name}"
    )
    to = (envelope.from_addr if envelope else "") or "(sender unknown: forward manually)"
    return KickbackDraft(
        to=to,
        subject=subject,
        body=body,
        code=code,  # type: ignore[arg-type]
        reason=reason,
        missing_fields=missing,
        chosen_by=chosen_by,
    )


# -------------------------------------------------------------------------------- classifier ----


class IntakeClassifier:
    """deterministic route -> (if ambiguous, or policy=always) Decider server -> chat classifier -> default."""

    def __init__(
        self,
        client: DeciderClient | None = None,
        llm: Any = None,
        *,
        policy: Policy = "auto",
        threshold: float = DEFAULT_THRESHOLD,
        cooldown_s: float = 30.0,
        ocr_available: bool | None = None,
        owner_name: str = "the owner",
        business_name: str = "Accounts Payable",
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self.client = client
        self.llm = llm
        self.policy: Policy = policy
        self.threshold = float(threshold)
        self.cooldown_s = cooldown_s
        self._ocr = ocr_available
        self.owner_name = owner_name
        self.business_name = business_name
        self.max_tokens = max_tokens
        self.max_attempts = max_attempts
        self._lock = threading.Lock()
        self._down_until = 0.0
        self.last_error: str | None = None
        self.stats = {
            "classified": 0,
            "decider": 0,
            "hackathon-chat": 0,
            "deterministic": 0,
            "ambiguous": 0,
            "model_decisions": 0,
            "validation_failures": 0,
            "kickbacks": 0,
            "reviews": 0,
        }

    @classmethod
    def from_settings(
        cls, settings: Any, llm: Any = None, client: DeciderClient | None = None
    ) -> IntakeClassifier:
        if client is None and getattr(settings, "decider_active", False):
            client = HttpDeciderClient(settings.effective_decider_url, timeout_s=settings.decider_timeout_s)
        return cls(
            client,
            llm,
            policy=getattr(settings, "intake_classifier", "auto"),
            threshold=getattr(settings, "decider_min_confidence", DEFAULT_THRESHOLD),
            cooldown_s=getattr(settings, "decider_cooldown_s", 30.0),
            owner_name=getattr(settings, "owner_name", "the owner"),
            business_name=getattr(settings, "business_name", "Accounts Payable"),
        )

    @property
    def enabled(self) -> bool:
        """A Decider server is configured (the chat classifier is available whenever the LLM is)."""
        return self.client is not None

    @property
    def cooling_down(self) -> bool:
        return time.monotonic() < self._down_until

    @property
    def has_model(self) -> bool:
        """Some classifier (Decider server or chat model) is configured to settle ambiguous routes."""
        return self.client is not None or bool(self.llm is not None and getattr(self.llm, "enabled", False))

    def ocr_available(self) -> bool:
        if self._ocr is None:
            from vouch.intake.extract import ocr_backend

            self._ocr = ocr_backend() != "none"
        return self._ocr

    # -- the one entry point ---------------------------------------------------------------------------

    def classify(
        self,
        probes: list[DocumentProbe],
        envelope: EmailEnvelope | None = None,
        *,
        source: str = "email",
        extractor_used: str | None = None,
        missing_fields: Iterable[str] = (),
    ) -> IntakeClassification:
        missing = [f for f in missing_fields if f in REQUIRED_FIELDS]
        route = deterministic_route(probes, self.ocr_available())
        cls = IntakeClassification(
            engine="deterministic",
            policy=self.policy,
            format=route.format,
            tool=route.tool,
            format_confidence=1.0,
            tool_confidence=1.0,
            threshold=self.threshold,
            ambiguous=list(route.ambiguous),
            deterministic_format=route.format,
            deterministic_tool=route.tool,
            extractor_used=extractor_used,
            missing_fields=missing,
        )
        ask = self.policy == "always" or (self.policy == "auto" and not route.obvious)
        state = render_state(probes, envelope, source, missing)
        with self._lock:  # one invoice at a time; the questions of a chain run strictly in sequence
            by_model = False
            if ask and self.client is not None:
                by_model = self._ask_decider(state, cls, route)
            if ask and not by_model:
                by_model = self._ask_llm(state, cls, route)
            if by_model:
                cls.agrees_with_deterministic = (cls.format, cls.tool) == (route.format, route.tool)
                if not cls.agrees_with_deterministic:
                    cls.notes.append(f"deterministic route was {route.format} -> {route.tool}")
            else:
                self._decide_by_code(cls, route, asked=ask)
            # Readability is the deterministic layer's call: a model may add friction (kick back a readable
            # invoice for the owner to look at) but can never make unreadable input parseable.
            model_kick = by_model and (
                cls.format == "unreadable_or_unsupported" or cls.tool == "request_resubmission"
            )
            cls.kickback = route.code is not None or model_kick or bool(missing)
            if cls.kickback:
                self._kickback(cls, route, probes, envelope, state, model_kick=model_kick)
                self.stats["kickbacks"] += 1
            # Safe default: when code was unsure, a classifier was there to settle it and no answer survived
            # validation/admissibility, the deterministic default is only a guess, so the owner confirms the
            # routing; the card never pays on it. (With no classifier configured, deterministic routing is
            # the product and the kernel's own checks still gate every payment.)
            if ask and route.ambiguous and not by_model and not cls.kickback and self.has_model:
                self._require_review(cls, route)
            self._check_chain(cls)
        if extractor_used:
            tools = EXTRACTOR_TOOLS.get(extractor_used, ())
            cls.agrees_with_extractor = cls.tool in tools if tools else None
        for d in cls.decisions:
            if d.engine != "deterministic":
                cls.model_latency_ms += d.latency_ms
                cls.tokens += d.tokens
            cls.validation_failures += len(d.validation_errors)
        cls.model_latency_ms = round(cls.model_latency_ms, 1)
        self.stats["classified"] += 1
        self.stats[cls.engine] += 1
        self.stats["ambiguous"] += bool(route.ambiguous)
        self.stats["model_decisions"] += sum(d.engine != "deterministic" for d in cls.decisions)
        self.stats["validation_failures"] += cls.validation_failures
        self.stats["reviews"] += cls.review_required
        return cls

    def complete(
        self,
        prior: IntakeClassification,
        probes: list[DocumentProbe],
        envelope: EmailEnvelope | None = None,
        *,
        source: str = "email",
        extractor_used: str | None = None,
        missing_fields: Iterable[str] = (),
    ) -> IntakeClassification:
        """Finish a chain that ``classify`` settled *before* extraction (the live intake service).

        The format and tool decisions stand and no model is consulted again; this adds what extraction
        revealed: the extractor that actually ran, and - readability being code's call - a deterministic
        kickback when the chosen tool found nothing usable (``unreadable_scan`` after OCR of a blank scan)
        or the kernel could not find a required field (``missing_fields``). As in ``classify``, a kickback
        hold supersedes the routing review (one owner action, never a payment); the adopted chain is
        re-validated as one unit.
        """
        cls = prior.model_copy(deep=True)
        cls.missing_fields = [f for f in missing_fields if f in REQUIRED_FIELDS]
        cls.extractor_used = extractor_used
        cls.agrees_with_extractor = None
        if extractor_used:
            tools = EXTRACTOR_TOOLS.get(extractor_used, ())
            cls.agrees_with_extractor = cls.tool in tools if tools else None
        with self._lock:
            after = deterministic_route(probes, self.ocr_available())
            if not cls.kickback and (after.code is not None or cls.missing_fields):
                route = (
                    after
                    if after.code is not None
                    else Route(
                        format=cls.deterministic_format,
                        tool=cls.deterministic_tool,
                        ambiguous=list(cls.ambiguous),
                    )
                )
                state = render_state(probes, envelope, source, cls.missing_fields)
                cls.kickback = True
                self._kickback(cls, route, probes, envelope, state, model_kick=False)
                cls.notes.append(f"after extraction: {cls.kickback_reason}")
                self.stats["kickbacks"] += 1
                if cls.review_required:
                    self._lift_review(cls)
            self._check_chain(cls)
        return cls

    def _lift_review(self, cls: IntakeClassification) -> None:
        """Same rule as ``classify``: a kickback hold already keeps the card from paying, so the routing
        review (owner confirms the guessed route) is not asked on top of it."""
        cls.review_required, cls.review_reason = False, None
        cls.notes = [n for n in cls.notes if not n.startswith("owner review required")]
        self.stats["reviews"] -= 1

    def _require_review(self, cls: IntakeClassification, route: Route) -> None:
        why = cls.fallback_reason or "no classifier available"
        cls.review_required = True
        cls.review_reason = (
            f"ambiguous ({', '.join(route.ambiguous)}); no classifier answer was accepted ({why}); "
            f"deterministic default {route.format} -> {route.tool} is not trusted for payment"
        )
        cls.notes.append("owner review required: " + cls.review_reason)

    @staticmethod
    def _check_chain(cls: IntakeClassification) -> None:
        """The adopted chain, whatever engine produced it, must validate as one unit (last line of defence
        against an inconsistent format/tool pair reaching the card)."""
        payload: dict[str, Any] = {
            "format": {"answer": cls.format, "reason_code": NOT_STATED},
            "tool": {"format": cls.format, "answer": cls.tool, "reason_code": NOT_STATED},
        }
        if cls.kickback_code:
            payload["kickback"] = {"answer": cls.kickback_code, "reason_code": NOT_STATED}
        try:
            IntakeDecisionChain.model_validate(payload)
        except Exception as exc:  # pragma: no cover - deterministic routes are consistent by construction
            cls.review_required = True
            cls.review_reason = f"inconsistent decision chain: {exc}"
            cls.notes.append("owner review required: " + cls.review_reason)

    def _decide_by_code(self, cls: IntakeClassification, route: Route, *, asked: bool) -> None:
        cls.engine = "deterministic"
        cls.format, cls.tool = route.format, route.tool
        cls.format_confidence = cls.tool_confidence = 1.0
        cls.agrees_with_deterministic = True
        if not route.ambiguous:
            why = "obvious from MIME type / extension / bytes"
        elif asked:
            why = f"ambiguous ({', '.join(route.ambiguous)}); no model answer accepted, default used"
        else:
            why = f"ambiguous ({', '.join(route.ambiguous)}); INTAKE_CLASSIFIER={self.policy}, default used"
            cls.notes.append(why)
        single = len(TOOLS_FOR_FORMAT[route.format]) == 1
        cls.decisions.append(
            decided(
                "format", FORMAT_QUESTION, route.format, engine="deterministic", note=f"{why}: {route.basis}"
            )
        )
        cls.decisions.append(
            decided(
                "tool",
                TOOL_QUESTION,
                route.tool,
                engine="deterministic",
                note=f"the only tool for {route.format}" if single else route.basis,
            )
        )

    # -- engines -------------------------------------------------------------------------------------

    def _ask_decider(self, state: str, cls: IntakeClassification, route: Route) -> bool:
        assert self.client is not None
        if self.cooling_down:
            cls.fallback_reason = f"decider skipped: cooling down after a failure ({self.last_error})"
            return False
        ocr = self.ocr_available()
        try:
            fmt = self._decider_question(state, cls, FORMAT_QUESTION, set(route.admissible_formats))
            if fmt is None:
                return False
            if fmt == "unreadable_or_unsupported":
                tool = "request_resubmission"
                cls.decisions.append(
                    decided("tool", TOOL_QUESTION, tool, engine="deterministic", note="implied by the format")
                )
            else:
                tool = self._decider_question(
                    state, cls, tool_question_for(fmt), admissible_tools(fmt, ocr), fmt=fmt
                )
                if tool is None:
                    return False
        except DeciderUnavailable as exc:
            self.last_error = str(exc)
            self._down_until = time.monotonic() + self.cooldown_s
            cls.fallback_reason = f"decider unreachable: {exc}"
            log.warning("decider unavailable, falling back: %s", exc)
            return False
        except DeciderRejected as exc:
            self.last_error = str(exc)
            cls.fallback_reason = f"decider answer rejected: {exc}"
            log.warning("decider answer rejected, falling back: %s", exc)
            return False
        self.last_error = None
        cls.engine = "decider"
        cls.format, cls.tool = fmt, tool  # type: ignore[assignment]
        confs = {d.key: d.confidence for d in cls.decisions if d.engine == "decider" and d.accepted}
        cls.format_confidence = confs.get("format")
        cls.tool_confidence = confs.get("tool", cls.format_confidence)
        return True

    def _decider_question(
        self,
        state: str,
        cls: IntakeClassification,
        question: Question,
        admissible: set[str],
        *,
        fmt: str | None = None,
    ) -> str | None:
        """One Decider ``choice`` question; records the decision; returns the accepted answer or None."""
        assert self.client is not None
        text = question.text if fmt is None else f"The submission format is {fmt}. {question.text}"
        criteria = dict(question.criteria)
        record = Decision(
            key=question.key, question=question.text, options=list(question.options), engine="decider"
        )
        cls.decider_calls += 1  # attempts, so a failed request still shows up in the audit record
        try:
            resp = self.client.ask(state, {question.key: choice(text, criteria)})
        except (DeciderUnavailable, DeciderRejected) as exc:
            record.error, record.attempts = f"{type(exc).__name__}: {exc}", 1
            cls.decisions.append(record)
            raise
        self._fill_from_decider(record, resp)
        cls.decider_model = resp.model
        cls.decider_latency_ms = round((cls.decider_latency_ms or 0.0) + (resp.latency_ms or 0.0), 1)
        answer = resp.answers.get(question.key)
        if not isinstance(answer, ChoiceAnswer):
            record.error = f"missing or non-choice answer for {question.key!r}"
            cls.decisions.append(record)
            raise DeciderRejected(record.error)
        record.answer, record.confidence = answer.choice, round(float(answer.confidence), 4)
        # The same strict model the chat path is validated with: enum answer, and for the tool question the
        # format/tool consistency check (a Decider answering csv_reader for a PDF is rejected here).
        payload: dict[str, Any] = {"answer": answer.choice, "reason_code": NOT_STATED}
        if fmt is not None and "format" in question.output_model.model_fields:
            payload["format"] = fmt
        validated, errors = validate_decision(question, payload)
        if validated is None:
            record.validation_errors.extend(errors)
            record.error = f"{question.key!r} answer {answer.choice!r} failed validation: {'; '.join(errors)}"
            cls.decisions.append(record)
            raise DeciderRejected(record.error)
        if answer.choice not in admissible:
            record.note = f"answer {answer.choice!r} is not admissible for this evidence"
            cls.decisions.append(record)
            cls.fallback_reason = f"decider {question.key} {record.note}"
            return None
        if answer.confidence < self.threshold:
            record.note = f"confidence {answer.confidence:.2f} < {self.threshold:.2f}"
            cls.decisions.append(record)
            cls.fallback_reason = f"decider {question.key} {record.note}"
            return None
        record.accepted = True
        cls.decisions.append(record)
        return answer.choice

    @staticmethod
    def _fill_from_decider(record: Decision, resp: SystemOneResponse) -> None:
        record.attempts = 1
        record.latency_ms = round(float(resp.latency_ms or 0.0), 1)
        record.input_tokens = int(resp.usage.input_tokens)
        record.output_tokens = int(resp.usage.output_tokens)

    def _ask_llm(self, state: str, cls: IntakeClassification, route: Route) -> bool:
        llm = self.llm
        if llm is None or not getattr(llm, "enabled", False):
            cls.notes.append("hackathon-chat classifier unavailable (LLM offline); deterministic route used")
            return False
        fmt_d = self._llm_question(cls, FORMAT_QUESTION, state, set(route.admissible_formats))
        if not fmt_d.accepted:
            cls.fallback_reason = f"hackathon-chat format decision rejected: {fmt_d.error or fmt_d.note}"
            return False
        fmt = str(fmt_d.answer)
        if fmt == "unreadable_or_unsupported":
            tool = "request_resubmission"
            cls.decisions.append(
                decided("tool", TOOL_QUESTION, tool, engine="deterministic", note="implied by the format")
            )
        else:
            tool_d = self._llm_question(
                cls,
                tool_question_for(fmt),
                f"The submission format is {fmt}.\n{state}",
                admissible_tools(fmt, self.ocr_available()),
            )
            if not tool_d.accepted:
                cls.fallback_reason = f"hackathon-chat tool decision rejected: {tool_d.error or tool_d.note}"
                return False
            tool = str(tool_d.answer)
        cls.engine = "hackathon-chat"
        cls.format, cls.tool = fmt, tool  # type: ignore[assignment]
        cls.format_confidence = cls.tool_confidence = None  # no calibrated confidence from a chat model
        return True

    def _llm_question(
        self, cls: IntakeClassification, question: Question, evidence: str, admissible: set[str]
    ) -> Decision:
        d = self.llm.decide(
            question,
            evidence,
            admissible=admissible,
            role=f"classify:{question.key}",
            max_tokens=self.max_tokens,
            max_attempts=self.max_attempts,
        )
        if d is None:
            d = Decision(
                key=question.key,
                question=question.text,
                options=list(question.options),
                engine="hackathon-chat",
                error="no model available for this question",
            )
        d.engine = "hackathon-chat"
        cls.llm_calls += 1
        cls.decisions.append(d)
        return d

    # -- kickback -----------------------------------------------------------------------------------

    def _kickback(
        self,
        cls: IntakeClassification,
        route: Route,
        probes: list[DocumentProbe],
        envelope: EmailEnvelope | None,
        state: str,
        *,
        model_kick: bool,
    ) -> None:
        """Pick the reply template (a reason code) and render the draft. Code decides whenever it knows
        why; a model that added friction on readable input may only pick the code (question 3)."""
        chooser: Engine = "deterministic"
        if route.code is not None:
            code, detail = route.code, route.detail or route.basis
        elif cls.missing_fields and not model_kick:
            code = "missing_fields"
            detail = f"readable, but the kernel could not find: {', '.join(cls.missing_fields)}"
        else:
            code = self._model_reason(cls, state)
            if code is None:
                code, detail = (
                    "ambiguous_submission",
                    f"{cls.engine} classified the submission as not processable",
                )
            else:
                chooser, detail = cls.engine, f"{cls.engine} picked the {code} template"
        if chooser == "deterministic":
            cls.decisions.append(
                decided("kickback_reason", REASON_QUESTION, code, engine="deterministic", note=detail)
            )
        cls.kickback_code = code  # type: ignore[assignment]
        cls.kickback_reason = detail
        cls.kickback_draft = render_kickback(
            code,
            envelope,
            [p.filename for p in probes if p.sniffed_kind != "email_body"],
            reason=detail,
            missing_fields=cls.missing_fields,
            chosen_by=chooser,
            owner_name=self.owner_name,
            business_name=self.business_name,
        )

    def _model_reason(self, cls: IntakeClassification, state: str) -> str | None:
        if cls.engine == "decider" and self.client is not None:
            try:
                return self._decider_question(state, cls, REASON_QUESTION, set(KICKBACK_REASONS))
            except (DeciderUnavailable, DeciderRejected) as exc:
                log.warning("decider kickback reason failed: %s", exc)
                return None
        if cls.engine == "hackathon-chat":
            d = self._llm_question(cls, REASON_QUESTION, state, set(KICKBACK_REASONS))
            return d.answer if d.accepted else None
        return None

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "policy": self.policy,
            "client": getattr(self.client, "name", None),
            "threshold": self.threshold,
            "cooling_down": self.cooling_down,
            "last_error": self.last_error,
            "schemas": ["FormatDecision", "ToolDecision", "KickbackDecision"],
            **self.stats,
        }


def scripted_answer(
    option: str, *, format: str | None = None, reason_code: str | None = None
) -> dict[str, Any]:
    """A ``ScriptedModel`` tool turn for one of the three classifiers (tests and the red-team suite).

    The schema is inferred from the option (formats, tools and kickback codes are disjoint); an option
    outside every enum is sent as a ``FormatDecision`` so the schema rejects it. For a tool answer the
    echoed ``format`` defaults to the first format that tool serves; pass ``format=`` to script a model
    that echoes the real format but picks an inconsistent tool (the model-validator path).
    """
    if option in TOOLS:
        fmt = format or next(f for f, tools in TOOLS_FOR_FORMAT.items() if option in tools)
        return {
            "tool": "ToolDecision",
            "input": {"format": fmt, "answer": option, "reason_code": reason_code or "only_tool_for_format"},
        }
    if option in KICKBACK_REASONS:
        return {
            "tool": "KickbackDecision",
            "input": {"answer": option, "reason_code": reason_code or "unsure"},
        }
    return {
        "tool": "FormatDecision",
        "input": {"answer": option, "reason_code": reason_code or "file_extension"},
    }


def extractor_for(tool: str, kind: str = "") -> Callable[[bytes, str], ExtractedDocument] | None:
    """The deterministic extractor a tool decision maps to (``None`` for ``request_resubmission``).

    ``kind`` is the sniffed kind of the file the tool is applied to: ``image_ocr`` on a PDF means OCR of a
    scanned PDF, and the plain-text reader keeps an ``unknown`` kind on the record.
    """
    from vouch.intake import extract as ex

    if tool == "image_ocr":
        return ex.extract_pdf_ocr if kind == "pdf" else ex.extract_image
    if tool == "body_parser" and kind == "unknown":
        return partial(ex.extract_text, kind="unknown")
    table: dict[str, Callable[[bytes, str], ExtractedDocument]] = {
        "pdf_text": ex.extract_pdf,
        "excel_reader": ex.extract_xlsx,
        "csv_reader": ex.extract_csv,
        "body_parser": ex.extract_text,
    }
    return table.get(tool)


__all__ = [
    "AMBIGUITY",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_THRESHOLD",
    "EXTRACTOR_TOOLS",
    "FIELD_LABELS",
    "FORMATS",
    "FORMAT_CRITERIA",
    "FORMAT_QUESTION",
    "KICKBACK_REASONS",
    "KINDS_FOR_TOOL",
    "REASON_CRITERIA",
    "REASON_QUESTION",
    "REQUIRED_FIELDS",
    "TEMPLATES",
    "TOOLS",
    "TOOLS_FOR_FORMAT",
    "TOOL_CRITERIA",
    "TOOL_QUESTION",
    "Decision",
    "DocumentProbe",
    "FormatDecision",
    "IntakeClassification",
    "IntakeClassifier",
    "IntakeDecisionChain",
    "KickbackDecision",
    "KickbackDraft",
    "Route",
    "ToolDecision",
    "admissible_tools",
    "deterministic_route",
    "extractor_for",
    "probes_from_documents",
    "probes_from_files",
    "probes_from_submission",
    "render_kickback",
    "render_state",
    "scripted_answer",
    "tool_question_for",
]
