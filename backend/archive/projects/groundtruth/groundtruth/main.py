"""groundtruth API: the HTTP backend the (separate) frontend talks to."""

import httpx
from fastapi import APIRouter

from groundtruth import __version__
from groundtruth.config import get_settings
from hm_api_common import create_app, run

settings = get_settings()
router = APIRouter(prefix="/v1", tags=["groundtruth"])


@router.get("/info")
def info() -> dict:
    return {
        "project": "groundtruth",
        "description": "Photo-proof construction milestone payments: verify site evidence against milestones before releasing funds.",
        "status": "skeleton",
    }


# TODO: add the endpoints the frontend needs, e.g.
#   POST /v1/runs                -> agents.build_agent()(prompt); return result or pending approvals
#   POST /v1/runs/{id}/approve   -> resume with hm_agents_common.approval.approval_responses(...)


async def inference_ready() -> bool:
    async with httpx.AsyncClient(timeout=1.0) as client:
        return (await client.get(f"{settings.inference_url}/health")).status_code == 200


app = create_app("groundtruth-api", __version__, readiness_checks={"inference": inference_ready})
app.include_router(router)


def main() -> None:
    run("groundtruth.main:app", port=settings.port)


if __name__ == "__main__":
    main()
