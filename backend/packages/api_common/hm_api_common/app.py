"""FastAPI app factory shared by every project API and inference service."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from hm_core.config import AppSettings, get_app_settings
from hm_core.errors import AppError
from hm_core.logging import configure_logging

log = logging.getLogger("hm.api")

# Return True when ready; raise or return False otherwise. Sync or async.
ReadinessCheck = Callable[[], bool | Awaitable[bool]]


def _install_middleware(app: FastAPI, settings: AppSettings) -> None:
    origins = settings.cors_allow_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials="*" not in origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_logging(request: Request, call_next: Callable[[Request], Awaitable[Any]]) -> Any:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error", extra={"request_id": request_id, "path": request.url.path})
            response = JSONResponse(
                {"error": {"code": "internal_error", "message": "internal error", "details": {}}},
                status_code=500,
            )
        response.headers["X-Request-ID"] = request_id
        if request.url.path not in ("/health", "/ready"):
            log.info(
                "%s %s -> %s",
                request.method,
                request.url.path,
                response.status_code,
                extra={"request_id": request_id, "ms": round((time.perf_counter() - start) * 1000, 1)},
            )
        return response


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(exc.to_dict(), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        body = {"error": {"code": "validation_failed", "message": "invalid request", "details": exc.errors()}}
        return JSONResponse(body, status_code=422)


def create_app(
    name: str,
    version: str = "0.1.0",
    *,
    settings: AppSettings | None = None,
    readiness_checks: dict[str, ReadinessCheck] | None = None,
    configure_logs: bool = True,
    **fastapi_kwargs: Any,
) -> FastAPI:
    """Build a FastAPI app with CORS, request logging, JSON errors, `/health` and `/ready`.

    `/health` is liveness (process up). `/ready` runs `readiness_checks` (DB, model loaded, ...).
    """
    settings = settings or get_app_settings()
    if configure_logs:
        configure_logging(settings.log_level, settings.log_json)
    app = FastAPI(title=name, version=version, **fastapi_kwargs)
    app.state.settings = settings
    checks = readiness_checks or {}

    _install_middleware(app, settings)
    _install_error_handlers(app)

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": name, "version": version, "env": settings.app_env}

    @app.get("/ready", tags=["ops"])
    async def ready() -> JSONResponse:
        results: dict[str, str] = {}
        for check_name, check in checks.items():
            try:
                outcome = check()
                if hasattr(outcome, "__await__"):
                    outcome = await outcome  # type: ignore[misc]
                results[check_name] = "ok" if outcome else "fail"
            except Exception as exc:
                results[check_name] = f"error: {type(exc).__name__}"
        ok = all(v == "ok" for v in results.values())
        return JSONResponse(
            {"status": "ok" if ok else "degraded", "checks": results}, status_code=200 if ok else 503
        )

    return app


def run(app_path: str, port: int, host: str = "0.0.0.0", reload: bool = False) -> None:  # noqa: S104
    import uvicorn

    uvicorn.run(app_path, host=host, port=port, reload=reload, log_config=None)
