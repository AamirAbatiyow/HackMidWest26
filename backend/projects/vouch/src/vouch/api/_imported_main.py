"""vouch API: the HTTP backend the (separate) frontend talks to. OpenAPI docs at /docs."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import date
from typing import Any

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from vouch import __version__
from vouch.cards import PaymentCard
from vouch.config import get_settings
from vouch.domain import CardStatus, Lane, Resolution, Vendor
from vouch.funding import recommend
from vouch.kernel import format_cents
from vouch.engine import VouchEngine, Run, Submission
from hm_agents_common.tracing import setup_tracing
from hm_api_common import create_app, run
from hm_core.errors import NotFoundError, ValidationFailedError

settings = get_settings()
router = APIRouter(prefix="/v1", tags=["vouch"])
_state: dict[str, Any] = {"service": None, "redteam": None}
_ops = threading.RLock()


def get_service() -> VouchEngine:
    if _state["service"] is None:
        from vouch.demo import seed

        svc = VouchEngine(settings=settings)
        seed(svc)
        _state["service"] = svc
    return _state["service"]


def set_service(service: VouchEngine | None) -> None:
    _state["service"] = service


# --- views ---------------------------------------------------------------------------------------------


def run_view(r: Run, full: bool = False) -> dict[str, Any]:
    cards = r.card_list()
    payable = [c for c in cards if c.status != CardStatus.CREDIT]
    lanes: dict[str, int] = {}
    for c in payable:
        if c.policy:
            lanes[c.policy.lane.value] = lanes.get(c.policy.lane.value, 0) + 1
    paid = sum(c.payable_cents for c in payable if c.status == CardStatus.PAID)
    held = sum(c.payable_cents for c in payable if c.status == CardStatus.HOLD)
    return {
        "id": r.id,
        "label": r.label,
        "status": r.status,
        "created_at": r.created_at,
        "pending_approval": r.pending,
        "totals": {
            "cards": len(cards),
            "lanes": lanes,
            "paid_cents": paid,
            "held_cents": held,
            "payable_cents": sum(c.payable_cents for c in payable),
            "paid": format_cents(paid),
            "held": format_cents(held),
        },
        "cards": [c.model_dump(mode="json") if full else c.summary() for c in cards],
        "settlements": r.settlements,
        "node_ms": r.node_ms,
        "error": r.error,
    }


def _run(run_id: str) -> Run:
    r = get_service().runs.get(run_id)
    if r is None:
        raise NotFoundError(f"unknown run {run_id}")
    return r


# --- requests ------------------------------------------------------------------------------------------


class SubmitRequest(BaseModel):
    invoices: list[Submission] = Field(min_length=1, max_length=100)
    label: str = ""
    wait: bool = Field(
        True, description="Run synchronously; false returns immediately (poll or stream the run)"
    )


class TextSubmitRequest(BaseModel):
    text: str = Field(min_length=10, description="Invoice text, e.g. extracted from a PDF")
    submitted_by: str = "ap-inbox"
    delivery_confirmed: bool = False
    po_number: str | None = None
    wait: bool = True


class ApprovalRequest(BaseModel):
    approved: bool = True
    card_ids: list[str] | None = Field(None, description="Subset of cards to pay; default: all READY cards")
    approver: str = "owner"
    note: str = ""


class ActorNote(BaseModel):
    actor: str = "owner"
    note: str = ""


class ConfirmBankRequest(ActorNote):
    phone_called: str = Field(description="Must be the phone number already on the vendor master file")
    method: str | None = None


class AppealRequest(BaseModel):
    vendor_contact: str = "vendor"
    message: str = Field(min_length=3)


# --- endpoints -----------------------------------------------------------------------------------------


@router.get("/info")
def info() -> dict[str, Any]:
    svc = get_service()
    return {
        "project": "vouch",
        "description": "Payment trust layer: keeps irreversible stablecoin payouts away from bad actors without slowing honest vendors.",
        "business": settings.business_name,
        "owner": settings.owner_name,
        "today": svc.today.isoformat(),
        "llm_mode": svc.llm.mode,
        "llm_provider": svc.llm.provider(),
        "scorer": getattr(svc.scorer(), "name", "?"),
        "settlement_adapter": svc.adapter.name,
        "settlement_network": svc.adapter.network,
        "vendors": len(svc.vendors),
        "limits_cents": {
            "approval": svc.limits.approval_limit_cents,
            "fast_pay": svc.limits.fast_pay_limit_cents,
            "single_payment": svc.limits.single_payment_limit_cents,
            "batch": svc.limits.batch_limit_cents,
        },
    }


@router.post("/demo/seed", summary="Load the scripted demo (vendor master + 6 invoices) and run it")
def demo_seed(execute_run: bool = Query(True, alias="run")) -> dict[str, Any]:
    from vouch.demo import OWNER_STORY, demo_submissions, seed
    from vouch.pipeline import execute

    svc = get_service()
    with _ops:
        seed(svc)
        if not execute_run:
            return {"seeded_vendors": len(svc.vendors), "story": OWNER_STORY}
        r = svc.new_run(demo_submissions(svc.today), label="demo: Friday vendor run")
        execute(svc, r)
    return {"story": OWNER_STORY, "run": run_view(r)}


def _start(svc: VouchEngine, r: Run, wait: bool) -> dict[str, Any]:
    from vouch.pipeline import execute

    def work() -> None:
        with _ops:
            try:
                execute(svc, r)
            except Exception:  # recorded on the run
                if wait:
                    raise

    if wait:
        work()
    else:
        threading.Thread(target=work, daemon=True).start()
    return run_view(r)


@router.post(
    "/invoices", summary="Submit invoices (JSON fields and/or raw PDF text) and run the payment graph"
)
def submit_invoices(req: SubmitRequest) -> dict[str, Any]:
    svc = get_service()
    r = svc.new_run(req.invoices, label=req.label)
    return _start(svc, r, req.wait)


@router.post("/invoices/text", summary="Submit one invoice as raw text (e.g. extracted from a PDF)")
def submit_invoice_text(req: TextSubmitRequest) -> dict[str, Any]:
    svc = get_service()
    sub = Submission(
        text=req.text,
        submitted_by=req.submitted_by,
        delivery_confirmed=req.delivery_confirmed,
        po_number=req.po_number,
    )
    r = svc.new_run([sub], label="text invoice")
    return _start(svc, r, req.wait)


@router.get("/runs")
def list_runs() -> list[dict[str, Any]]:
    return [{k: v for k, v in run_view(r).items() if k != "cards"} for r in get_service().runs.values()]


@router.get("/runs/{run_id}")
def get_run(run_id: str, full: bool = False) -> dict[str, Any]:
    return run_view(_run(run_id), full=full)


@router.get("/runs/{run_id}/events", summary="Run events after a sequence number (polling)")
def run_events(run_id: str, after: int = 0) -> dict[str, Any]:
    r = _run(run_id)
    return {"status": r.status, "events": [e for e in r.events if e["seq"] > after]}


@router.get(
    "/runs/{run_id}/stream", summary="Server-sent events for a run (node progress, decisions, settlements)"
)
async def run_stream(run_id: str, after: int = 0) -> StreamingResponse:
    r = _run(run_id)

    async def gen() -> Any:
        seq = after
        idle = 0
        while True:
            new = [e for e in r.events if e["seq"] > seq]
            for e in new:
                seq = e["seq"]
                yield f"id: {seq}\nevent: {e['type']}\ndata: {json.dumps(e, default=str)}\n\n"
            if r.status in ("awaiting_approval", "completed", "failed") and not new:
                idle += 1
                if idle > 2:
                    yield f"event: end\ndata: {json.dumps({'status': r.status})}\n\n"
                    return
            await asyncio.sleep(0.25)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post(
    "/runs/{run_id}/approve",
    summary="Owner answers the approval interrupt; approved cards settle as one batch",
)
def approve_run(run_id: str, req: ApprovalRequest) -> dict[str, Any]:
    from vouch.pipeline import approve

    svc = get_service()
    r = _run(run_id)
    with _ops:
        approve(svc, r, req.model_dump())
    return run_view(r)


@router.post(
    "/runs/{run_id}/settle", summary="Run a batch settle for every READY card (same approval + policy path)"
)
def settle_run(run_id: str, approver: str = "owner") -> dict[str, Any]:
    return approve_run(run_id, ApprovalRequest(approved=True, approver=approver))


@router.get(
    "/cards", summary="Payment cards with risk class, scores, LIME factors, legitimacy and policy decision"
)
def list_cards(
    run_id: str | None = None, lane: Lane | None = None, status: CardStatus | None = None
) -> list[dict[str, Any]]:
    svc = get_service()
    runs = [_run(run_id)] if run_id else list(svc.runs.values())
    cards = [c for r in runs for c in r.card_list()]
    if lane:
        cards = [c for c in cards if c.policy and c.policy.lane == lane]
    if status:
        cards = [c for c in cards if c.status == status]
    return [c.summary() for c in cards]


@router.get("/cards/{card_id}", response_model=PaymentCard)
def get_card(card_id: str) -> PaymentCard:
    return get_service().find_card(card_id)[1]


def _resolve(card_id: str, resolution: Resolution, phone_called: str | None = None) -> PaymentCard:
    with _ops:
        return get_service().resolve(card_id, resolution, phone_called=phone_called)


@router.post(
    "/cards/{card_id}/approve",
    response_model=PaymentCard,
    summary="Approve and pay one card (policy re-checked)",
)
def approve_card(card_id: str, req: ActorNote) -> PaymentCard:
    from vouch.pipeline import approve

    svc = get_service()
    r, card = svc.find_card(card_id)
    if card.status == CardStatus.HOLD:
        raise ValidationFailedError(
            "card is on hold; resolve it first",
            details={"required_actions": card.policy.required_actions if card.policy else []},
        )
    with _ops:
        approve(svc, r, {"approved": True, "card_ids": [card_id], "approver": req.actor, "note": req.note})
    return card


@router.post("/cards/{card_id}/hold", response_model=PaymentCard, summary="Owner places a manual hold")
def hold_card(card_id: str, req: ActorNote) -> PaymentCard:
    return _resolve(card_id, Resolution(kind="owner_hold", actor=req.actor, note=req.note))


@router.post("/cards/{card_id}/release-hold", response_model=PaymentCard)
def release_hold(card_id: str, req: ActorNote) -> PaymentCard:
    return _resolve(card_id, Resolution(kind="release_hold", actor=req.actor, note=req.note))


@router.post(
    "/cards/{card_id}/confirm-bank",
    response_model=PaymentCard,
    summary="Log an out-of-band bank confirmation (call-back to the phone number on file)",
)
def confirm_bank(card_id: str, req: ConfirmBankRequest) -> PaymentCard:
    return _resolve(
        card_id,
        Resolution(kind="confirm_bank", actor=req.actor, note=req.note, method=req.method),
        phone_called=req.phone_called,
    )


@router.post(
    "/cards/{card_id}/resolve",
    response_model=PaymentCard,
    summary="Owner resolves a risk hold (duplicate/split/ring/high risk) with a note",
)
def resolve_card(card_id: str, req: ActorNote) -> PaymentCard:
    if not req.note.strip():
        raise ValidationFailedError("a note explaining the resolution is required")
    return _resolve(card_id, Resolution(kind="resolve_risk", actor=req.actor, note=req.note))


@router.post("/cards/{card_id}/override-limit", response_model=PaymentCard)
def override_limit(card_id: str, req: ActorNote) -> PaymentCard:
    if not req.note.strip():
        raise ValidationFailedError("a note explaining the override is required")
    return _resolve(card_id, Resolution(kind="limit_override", actor=req.actor, note=req.note))


@router.post(
    "/cards/{card_id}/appeal",
    response_model=PaymentCard,
    summary="Vendor appeal: recorded, prioritised for owner review",
)
def appeal_card(card_id: str, req: AppealRequest) -> PaymentCard:
    return _resolve(card_id, Resolution(kind="appeal", actor=req.vendor_contact, note=req.message))


@router.get("/vendors")
def list_vendors(limit: int = 50, demo_only: bool = True) -> list[dict[str, Any]]:
    vendors = list(get_service().vendors.values())
    if demo_only:
        vendors = [v for v in vendors if v.id.startswith("v-")] or vendors
    return [
        {
            "id": v.id,
            "name": v.name,
            "country": v.country,
            "created_days_ago": v.created_days_ago,
            "payments": len(v.history),
            "oob_verified": v.oob_verified,
        }
        for v in vendors[:limit]
    ]


@router.get("/vendors/{vendor_id}")
def get_vendor(vendor_id: str) -> dict[str, Any]:
    svc = get_service()
    v = svc.vendors.get(vendor_id)
    if v is None:
        raise NotFoundError(f"unknown vendor {vendor_id}")
    return {
        "vendor": v.model_dump(mode="json"),
        "graph": svc.graph.features(vendor_id),
        "linked_vendors": {
            k: [svc.vendors[o].name for o in ids] for k, ids in svc.graph.shared(vendor_id).items()
        },
    }


@router.put("/vendors/{vendor_id}", summary="Add or update a vendor on the master file")
def upsert_vendor(vendor_id: str, vendor: Vendor) -> dict[str, Any]:
    if vendor.id != vendor_id:
        raise ValidationFailedError("vendor id in path and body differ")
    get_service().load_vendors([vendor])
    return {"ok": True, "vendors": len(get_service().vendors)}


@router.get("/cash", summary="Cash-forecast stub and pay-now vs schedule recommendations for open cards")
def cash() -> dict[str, Any]:
    svc = get_service()
    open_cards = [
        c
        for r in svc.runs.values()
        for c in r.card_list()
        if c.status in (CardStatus.READY, CardStatus.APPROVED, CardStatus.HOLD)
    ]
    return {
        "today": svc.today.isoformat(),
        "forecast": svc.forecast.to_dict(svc.today),
        "recommendations": recommend(open_cards, svc.forecast, svc.today),
    }


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[min(int(p * len(s)), len(s) - 1)], 1)


@router.get(
    "/netz", summary="Service vitals: latency per graph node, LLM calls and tokens, rate-limit headroom"
)
@router.get("/stats", include_in_schema=False)
def netz() -> dict[str, Any]:
    from hm_llm.clients import akamai_limiter
    from hm_llm.settings import get_llm_settings

    svc = get_service()
    llm_settings = get_llm_settings()
    limiter = akamai_limiter(llm_settings)
    timings = {
        k: {"n": len(v), "p50_ms": _pct(v, 0.5), "p95_ms": _pct(v, 0.95)}
        for k, v in sorted(svc.timings.items())
    }
    cards = [c for r in svc.runs.values() for c in r.card_list()]
    return {
        "service": "vouch-api",
        "version": __version__,
        "runs": len(svc.runs),
        "cards": len(cards),
        "paid": sum(c.status == CardStatus.PAID for c in cards),
        "held": sum(c.status == CardStatus.HOLD for c in cards),
        "llm": {
            "mode": svc.llm.mode,
            "provider": svc.llm.provider(),
            "model": llm_settings.akamai_inference_model
            if svc.llm.provider() == "akamai"
            else llm_settings.bedrock_model_id,
            "limits": {
                "rpm": llm_settings.llm_requests_per_minute,
                "context_tokens": llm_settings.llm_max_context_tokens,
                "output_tokens": llm_settings.llm_max_output_tokens,
            },
            "rate_limit_remaining": limiter.remaining,
            **svc.llm.stats.to_dict(),
        },
        "latency": timings,
        "explanations": {
            "llm": sum(c.explanation_source == "llm" for c in cards),
            "template": sum(c.explanation_source == "template" for c in cards),
        },
        "scorer": getattr(svc.scorer(), "name", "?"),
        "settlement": {"adapter": svc.adapter.name, "network": svc.adapter.network},
    }


@router.get("/redteam", summary="Latest red-team results (runs the suite on first call)")
def redteam() -> dict[str, Any]:
    if _state["redteam"] is None:
        return redteam_run()
    return _state["redteam"]


@router.post("/redteam/run", summary="Run the adversarial suite now (scripted LLM, mock ledger, ~seconds)")
def redteam_run() -> dict[str, Any]:
    from vouch.redteam import run_suite

    svc = get_service()
    result = run_suite(settings, scorer=svc._scorer)
    result["ran_at"] = date.today().isoformat()
    _state["redteam"] = result
    return result


@router.get("/model", summary="Risk model metadata and held-out metrics")
def model_info() -> dict[str, Any]:
    from hm_ml_common import ModelRegistry

    svc = get_service()
    registry = ModelRegistry()
    version = registry.latest(settings.model_name)
    meta = registry.meta(settings.model_name, version) if version else {}
    return {
        "scorer": getattr(svc.scorer(), "name", "?"),
        "name": settings.model_name,
        "version": version,
        "metrics": meta.get("metrics", {}),
        "params": meta.get("params", {}),
    }


async def inference_ready() -> bool:
    if settings.scorer == "heuristic":
        return True
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            if (await client.get(f"{settings.inference_url}/health")).status_code == 200:
                return True
    except httpx.HTTPError:
        pass
    from hm_ml_common import ModelRegistry

    return ModelRegistry().latest(settings.model_name) is not None  # in-process model is fine too


app = create_app(
    "vouch-api",
    __version__,
    readiness_checks={"model": inference_ready},
    description="Vouch payment trust layer. Start with POST /v1/demo/seed, then GET /v1/cards.",
)
app.include_router(router)
setup_tracing("vouch-api")


def main() -> None:
    run("vouch.main:app", port=settings.port)


if __name__ == "__main__":
    main()
