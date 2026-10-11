"""inflow API: the HTTP backend the (separate) frontend talks to."""

import httpx
from fastapi import APIRouter

from hm_api_common import create_app, run
from inflow import __version__
from inflow.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/v1", tags=["inflow"])


@router.get("/info")
def info() -> dict:
    return {
        "project": "inflow",
        "description": "Negotiating agents for receivables: agents propose and negotiate payment terms with payers within policy limits.",
        "status": "skeleton",
    }


# TODO: add the endpoints the frontend needs, e.g.
#   POST /v1/runs                -> agents.build_agent()(prompt); return result or pending approvals
#   POST /v1/runs/{id}/approve   -> resume with hm_agents_common.approval.approval_responses(...)


async def inference_ready() -> bool:
    async with httpx.AsyncClient(timeout=1.0) as client:
        return (await client.get(f"{settings.inference_url}/health")).status_code == 200


app = create_app("inflow-api", __version__, readiness_checks={"inference": inference_ready})
app.include_router(router)


def main() -> None:
    run("inflow.main:app", port=settings.port)


if __name__ == "__main__":
    main()
