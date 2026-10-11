"""Frontend-contract routes (served under ``/v1`` and unversioned; the client tries ``/v1`` first).

GET  /payments, /payments/{id}            payment queue in the shape the React app renders
POST /payments/{id}/approve|hold|appeal   owner actions ({"note": "..."}); Cedar-authorized, audited
GET  /payments/{id}/decisions             intake decision chain (question, options, answer, engine, cost)
GET  /outbox                              kickback drafts to senders; POST /payments/{id}/kickback/approve|decline
POST /batch/settle                        {"payment_ids": [...], "funding": "now"|"scheduled"} -> receipt
GET  /fairness                            held-out model metrics in the fairness report's shape
GET  /health, /info, /netz, /redteam      (unversioned; the /v1 versions live in cards.py / main.py)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from vouch.api.health import HealthProbes, health_html, health_json
from vouch.api.schemas import ActionBody, SettleBody
from vouch.api.state import get_service

payments = APIRouter(tags=["frontend"])
root = APIRouter(tags=["frontend"])
_probes: dict[str, HealthProbes] = {}


def _probe() -> HealthProbes:
    svc = get_service()
    p = _probes.get("p")
    if p is None or p.service is not svc:
        p = _probes["p"] = HealthProbes(svc)
    return p


@payments.get("/payments", summary="Payment queue (frontend shape)")
def list_payments() -> list[dict[str, Any]]:
    return get_service().payments()


@payments.get("/payments/{payment_id}")
def get_payment(payment_id: str) -> dict[str, Any]:
    return get_service().payment(payment_id)


@payments.post("/payments/{payment_id}/approve", summary="Owner approves (verifies a held card first)")
def approve_payment(payment_id: str, body: ActionBody | None = None) -> dict[str, Any]:
    body = body or ActionBody()
    return get_service().approve(payment_id, body.note, body.author)


@payments.post("/payments/{payment_id}/hold", summary="Owner places a hold (never a denial)")
def hold_payment(payment_id: str, body: ActionBody | None = None) -> dict[str, Any]:
    body = body or ActionBody()
    return get_service().hold(payment_id, body.note, body.author)


@payments.post("/payments/{payment_id}/appeal", summary="'Vendor is fine': owner vouches for the vendor")
def appeal_payment(payment_id: str, body: ActionBody | None = None) -> dict[str, Any]:
    body = body or ActionBody()
    return get_service().appeal(payment_id, body.note, body.author)


@payments.get("/payments/{payment_id}/audit", summary="Audit trail for one payment")
def payment_audit(payment_id: str) -> dict[str, Any]:
    return get_service().audit(payment_id)


@payments.get(
    "/payments/{payment_id}/decisions",
    summary="Intake decision chain (format -> extraction tool -> kickback reason) with cost and engine",
)
def payment_decisions(payment_id: str) -> dict[str, Any]:
    view = get_service().payment(payment_id)
    intake = view.get("intake") or {}
    return {
        "payment_id": payment_id,
        "engine": intake.get("engine"),
        "policy": intake.get("policy"),
        "ambiguous": intake.get("ambiguous", []),
        "format": intake.get("format"),
        "tool": intake.get("tool"),
        "kickback": intake.get("kickback", False),
        "kickback_code": intake.get("kickback_code"),
        "model_calls": (intake.get("decider_calls") or 0) + (intake.get("llm_calls") or 0),
        "model_latency_ms": intake.get("model_latency_ms", 0.0),
        "tokens": intake.get("tokens", 0),
        "decisions": intake.get("decisions", []),
    }


@payments.get(
    "/outbox",
    summary="Kickback drafts to senders (awaiting_owner | approved | declined); nothing here is auto-sent",
)
def outbox(status: str | None = None) -> list[dict[str, Any]]:
    return get_service().outbox(status)


@payments.post(
    "/payments/{payment_id}/kickback/approve",
    summary="Owner clears the drafted kickback email for sending (Cedar P-08; the hold stays)",
)
def approve_kickback(payment_id: str, body: ActionBody | None = None) -> dict[str, Any]:
    body = body or ActionBody()
    return get_service().kickback_decide(payment_id, True, body.note, body.author)


@payments.post(
    "/payments/{payment_id}/kickback/decline",
    summary="Owner declines the drafted kickback email (Cedar P-08)",
)
def decline_kickback(payment_id: str, body: ActionBody | None = None) -> dict[str, Any]:
    body = body or ActionBody()
    return get_service().kickback_decide(payment_id, False, body.note, body.author)


@payments.post(
    "/batch/settle", summary="Settle a batch (real XRPL testnet tx ids with SETTLEMENT_ADAPTER=xrpl)"
)
def settle_batch(body: SettleBody) -> dict[str, Any]:
    return get_service().settle(body.payment_ids, body.funding, body.author, body.note or "")


@payments.get(
    "/receipts/{tx_id}", summary="Settlement record for a transaction id (the mock ledger's 'explorer')"
)
def receipt(tx_id: str) -> dict[str, Any]:
    return get_service().receipt(tx_id)


@payments.get("/fairness", summary="Held-out model metrics in the frontend's fairness-report shape")
def fairness() -> dict[str, Any]:
    from hm_ml_common import ModelRegistry

    svc = get_service()
    s = svc.settings
    try:
        registry = ModelRegistry(s.model_registry_dir)
        version = registry.latest(s.model_name)
        metrics = registry.meta(s.model_name, version).get("metrics", {}) if version else {}
    except Exception:
        version, metrics = None, {}
    if not metrics:
        return {}
    cards = [c for r in svc.engine.runs.values() for c in r.card_list()]
    held = [c for c in cards if c.policy and c.policy.lane.value == "hold"]
    return {
        "period": f"held-out synthetic evaluation · model {version}",
        "heldShare": round(float(metrics.get("system_honest_hold_rate", 0.0)), 4),
        "newSmallVendorsOnTime": round(1.0 - float(metrics.get("system_honest_unusual_hold_rate", 0.0)), 4),
        "fraudCaught": {
            "count": round(
                float(metrics.get("system_n_bad", 0)) * float(metrics.get("system_bad_actor_catch_rate", 0))
            ),
            "amount": sum(c.payable_cents for c in held) / 100,
            "examples": [f"{c.invoice.vendor_name} {c.invoice.invoice_number}" for c in held[:3]],
        },
        "model_metrics": metrics,
        "model_version": version,
    }


# --- unversioned vitals ----------------------------------------------------------------------------------


def _wants_html(request: Request) -> bool:
    fmt = request.query_params.get("format")
    if fmt:
        return fmt == "html"
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept.split(",")[0]


@root.get("/health", summary="Liveness + which Akamai services are live (JSON, or HTML for a browser)")
def health(request: Request) -> Any:
    svc = get_service()
    if _wants_html(request):
        return HTMLResponse(health_html(svc, _probe()))
    return JSONResponse(health_json(svc, _probe()))


@root.get("/v1/health", summary="Cheap liveness for the frontend's 5-second poll")
def health_v1() -> dict[str, Any]:
    svc = get_service()
    from vouch import __version__

    return {
        "status": "ok",
        "service": "vouch-api",
        "version": __version__,
        "llm_mode": svc.engine.llm.mode,
        "scorer": getattr(svc.engine.scorer(), "name", "?"),
        "settlement_adapter": svc.engine.adapter.name,
        "database": svc.store.backend,
        "uptime_s": svc.uptime_s(),
    }


@root.get("/info", include_in_schema=False)
def info_root() -> dict[str, Any]:
    return get_service().info()


@root.get("/netz", include_in_schema=False)
def netz_root() -> dict[str, Any]:
    return get_service().netz()


@root.get("/redteam", include_in_schema=False)
def redteam_root() -> dict[str, Any]:
    return get_service().run_redteam()
