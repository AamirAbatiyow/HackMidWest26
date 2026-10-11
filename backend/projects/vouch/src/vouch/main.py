"""Vouch API: the HTTP backend the React frontend talks to. OpenAPI docs at /docs.

Routers:
- `api.frontend`  payments / batch settle / fairness (under /v1 and unversioned), /health, /info, /netz
- `api.cards`     the engine surface (/v1/runs, /v1/cards, owner resolutions, vendors, cash, redteam, model)
- `api.intake`    /v1/intake (JSON, .eml, file uploads), /v1/vendors/resolve, /v1/sender/check
"""

from __future__ import annotations

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse

from hm_agents_common.tracing import setup_tracing
from hm_api_common import create_app, run
from hm_core.config import AppSettings
from hm_core.errors import AppError
from vouch import __version__
from vouch.api import cards, frontend, intake, netstats, trust
from vouch.api.state import _state, get_engine, get_service, set_service  # noqa: F401  (re-exported for tests)
from vouch.config import get_settings

settings = get_settings()


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

    return ModelRegistry(settings.model_registry_dir).latest(settings.model_name) is not None


def store_ready() -> bool:
    return get_service().store.ping()[0]


app = create_app(
    "vouch-api",
    __version__,
    settings=AppSettings(cors_allow_origins=settings.cors_origin_list),
    readiness_checks={"model": inference_ready, "store": store_ready},
    description=(
        "Vouch payment trust layer. Frontend routes: GET /v1/payments, POST /v1/payments/{id}/approve|hold|appeal, "
        "POST /v1/batch/settle. Engine routes: POST /v1/demo/seed, GET /v1/cards, POST /v1/runs/{id}/approve. "
        "Intake: POST /v1/intake, /v1/intake/eml, /v1/intake/upload."
    ),
)
# The shared factory's /health is replaced by the Akamai-services health page (JSON + HTML).
app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/health"]


@app.exception_handler(AppError)
async def app_error(request: Request, exc: AppError) -> JSONResponse:
    body = exc.to_dict()
    body["detail"] = exc.message  # the frontend reads `detail` / `message`
    body["message"] = exc.message
    return JSONResponse(body, status_code=exc.status_code)


app.include_router(frontend.root)
app.include_router(frontend.payments, prefix="/v1")
app.include_router(frontend.payments)
app.include_router(cards.router)
app.include_router(intake.router)
app.include_router(netstats.router)
app.include_router(trust.router)
setup_tracing("vouch-api")


@app.on_event("startup")
def _warm() -> None:
    get_service()  # restore runs from the store (or seed the demo) before the first request


def main() -> None:
    run("vouch.main:app", port=settings.port, host=settings.host)


if __name__ == "__main__":
    main()
