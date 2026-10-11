"""Orchestrator timeline routes: the ordered steps a payment went through, with the tool or model that
actually ran each one, measured duration, status and a one-line result (``vouch.orchestration``).

GET /v1/runs/{run_id}/timeline        every card of a run (plus the per-node timings of the graph)
GET /v1/cards/{card_id}/timeline      one card
GET /v1/payments/{payment_id}/timeline   the same, under the frontend-contract path (also unversioned)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from hm_core.errors import NotFoundError
from vouch.api.state import get_engine
from vouch.orchestration import card_timeline, run_timeline

router = APIRouter(prefix="/v1", tags=["engine"])
payments = APIRouter(tags=["frontend"])


@router.get("/runs/{run_id}/timeline", summary="Orchestrator timeline for every card of a run")
def get_run_timeline(run_id: str) -> dict[str, Any]:
    engine = get_engine()
    run = engine.runs.get(run_id)
    if run is None:
        raise NotFoundError(f"unknown run {run_id}")
    return run_timeline(engine, run)


@router.get("/cards/{card_id}/timeline", summary="Orchestrator timeline for one card (steps, tools, timing)")
def get_card_timeline(card_id: str) -> dict[str, Any]:
    engine = get_engine()
    run, card = engine.find_card(card_id)
    return card_timeline(engine, run, card)


@payments.get("/payments/{payment_id}/timeline", summary="Orchestrator timeline (frontend path)")
def get_payment_timeline(payment_id: str) -> dict[str, Any]:
    return get_card_timeline(payment_id)
