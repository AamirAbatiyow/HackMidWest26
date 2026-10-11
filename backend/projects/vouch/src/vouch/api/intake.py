"""Intake routes (``/v1``): email JSON, raw .eml upload, file uploads, plus the two deterministic
checks on their own for debugging and demos (vendor resolution, sender check)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, UploadFile
from hm_core.errors import ValidationFailedError

from vouch.api.cards import run_view
from vouch.api.schemas import IntakeJsonBody, SenderCheckBody, VendorResolveBody
from vouch.api.state import get_engine, get_service
from vouch.contracts import VendorClaim, email_domain
from vouch.engine import Run
from vouch.intake import envelope_from_headers
from vouch.sender import check_sender
from vouch.vendors import resolve_vendor
from vouch.views import payment_view

router = APIRouter(prefix="/v1", tags=["intake"])

MAX_UPLOAD = 15 * 1024 * 1024


def _result(run: Run) -> dict[str, Any]:
    engine = get_engine()
    return {
        "run": run_view(run),
        "payments": [payment_view(engine, run, c) for c in run.card_list()],
    }


@router.post("/intake", summary="Email intake as JSON: headers + body + base64 attachments")
def intake_json(body: IntakeJsonBody) -> dict[str, Any]:
    return _result(get_service().intake(body.to_request()))


@router.post("/intake/eml", summary="Email intake from a raw .eml file (headers, body and attachments)")
async def intake_eml(file: Annotated[UploadFile, File()], submitted_by: Annotated[str, Form()] = "ap-inbox") -> dict[str, Any]:
    raw = await file.read()
    if not raw:
        raise ValidationFailedError("empty .eml upload")
    if len(raw) > MAX_UPLOAD:
        raise ValidationFailedError("upload too large")
    return _result(get_service().intake_eml(raw, submitted_by=submitted_by))


@router.post("/intake/upload", summary="Upload invoice files (PDF, image, XLSX, CSV, TXT); one invoice per request")
async def intake_upload(
    files: Annotated[list[UploadFile], File()],
    submitted_by: Annotated[str, Form()] = "ap-clerk",
    delivery_confirmed: Annotated[bool, Form()] = False,
    po_number: Annotated[str | None, Form()] = None,
    note: Annotated[str, Form()] = "",
) -> dict[str, Any]:
    payload: list[tuple[str, str | None, bytes]] = []
    for f in files:
        data = await f.read()
        if len(data) > MAX_UPLOAD:
            raise ValidationFailedError(f"{f.filename}: upload too large")
        payload.append((f.filename or "upload", f.content_type, data))
    if not payload:
        raise ValidationFailedError("no files")
    run = get_service().intake_files(
        payload, submitted_by=submitted_by, delivery_confirmed=delivery_confirmed, po_number=po_number, body_text=note
    )
    return _result(run)


@router.post("/vendors/resolve", summary="Deterministic vendor resolution for a claimed identity")
def vendors_resolve(body: VendorResolveBody) -> dict[str, Any]:
    svc = get_service()
    e = svc.engine
    claim = VendorClaim(**body.model_dump())
    res = resolve_vendor(
        claim,
        e.directory,
        sender_domain=email_domain(body.email),
        embedder=e.llm.embedder_or_none() if e.embedding_index is not None else None,
        index=e.embedding_index,
    )
    return res.model_dump()


@router.post("/sender/check", summary="SPF/DKIM/DMARC, lookalike-domain and reply-to checks for email headers")
def sender_check(body: SenderCheckBody) -> dict[str, Any]:
    e = get_engine()
    env = envelope_from_headers(body.headers)
    claimed = e.vendors.get(body.claimed_vendor_id or "")
    findings = check_sender(env, list(e.vendors.values()), claimed)
    return {**findings.model_dump(), "suspicious": findings.suspicious}
