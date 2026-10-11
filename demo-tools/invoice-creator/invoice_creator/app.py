"""FastAPI app: serves the single-page operator UI and the build/send API."""

from __future__ import annotations

import re
import secrets
from collections import OrderedDict
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from . import __version__
from .config import Settings, load_settings
from .deliver import deliver
from .mail import auth_summary, build_message, describe, eml_to_intake_json, message_bytes
from .models import BuiltMessage, Invoice, OutputFormat, SendLogEntry, SendRequest
from .presets import DEFAULT_STORY, build_presets, stories
from .render import Rendered, render

STATIC_DIR = Path(__file__).resolve().parent / "static"
RECEIVER_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{12}-[0-9a-f]{6}$")


class RenderRequest(BaseModel):
    invoice: Invoice
    format: OutputFormat = "pdf"


class Store:
    """Built messages (bounded, in memory + .eml on disk) and the send log (JSONL on disk)."""

    def __init__(self, data_dir: Path, keep: int = 300) -> None:
        self.data_dir = data_dir
        self.eml_dir = data_dir / "eml"
        self.log_path = data_dir / "send-log.jsonl"
        self.keep = keep
        self.built: OrderedDict[str, bytes] = OrderedDict()
        self.log: list[SendLogEntry] = []
        self.eml_dir.mkdir(parents=True, exist_ok=True)
        if self.log_path.exists():
            for line in self.log_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        self.log.append(SendLogEntry.model_validate_json(line))
                    except ValueError:
                        continue

    def new_id(self) -> str:
        return datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)

    def put(self, built_id: str, raw: bytes) -> None:
        self.built[built_id] = raw
        while len(self.built) > self.keep:
            self.built.popitem(last=False)
        (self.eml_dir / f"{built_id}.eml").write_bytes(raw)

    def get(self, built_id: str) -> bytes | None:
        raw = self.built.get(built_id)
        if raw is None:
            path = self.eml_dir / f"{built_id}.eml"
            if path.exists() and path.is_file() and path.parent == self.eml_dir:
                raw = path.read_bytes()
        return raw

    def append(self, entry: SendLogEntry) -> None:
        self.log.append(entry)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(entry.model_dump_json() + "\n")

    def clear(self) -> None:
        self.log.clear()
        if self.log_path.exists():
            self.log_path.unlink()


def _intake_preview(raw: bytes) -> dict:
    """The IntakeRequest JSON the receiver will forward, with attachment payloads elided."""
    j = eml_to_intake_json(raw)
    for a in j["attachments"]:
        a["data_b64"] = f"<{a['size']} bytes base64>"
    return j


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    store = Store(settings.data_dir)
    app = FastAPI(title="Vouch demo — invoice creator", version=__version__, docs_url="/api/docs")
    app.state.settings = settings
    app.state.store = store

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    @app.get("/app.js", include_in_schema=False)
    def app_js() -> FileResponse:
        return FileResponse(STATIC_DIR / "app.js", media_type="application/javascript")

    @app.get("/app.css", include_in_schema=False)
    def app_css() -> FileResponse:
        return FileResponse(STATIC_DIR / "app.css", media_type="text/css")

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": __version__, "sends_logged": len(store.log)}

    @app.get("/api/config")
    def config() -> dict:
        return {
            "smtp_host": settings.smtp_host,
            "smtp_port": settings.smtp_port,
            "mail_to": settings.mail_to,
            "backend_intake_url": settings.backend_intake_url,
            "backend_intake_format": settings.backend_intake_format,
            "receiver_inbound_url": settings.receiver_inbound_url,
            "receiver_api_url": settings.receiver_api_base,
            "intake_secret_configured": bool(settings.intake_shared_secret),
            "authserv_id": settings.authserv_id,
            "owner_name": settings.owner_name,
            "owner_address": settings.owner_address,
            "deliveries": settings.deliveries,
            "stories": [s.model_dump() for s in stories()],
            "default_story": DEFAULT_STORY,
            "version": __version__,
        }

    @app.get("/api/presets")
    def presets(story: str | None = None) -> list[dict]:
        """Every story's presets (each tagged with its ``story``), or one story's with ``?story=``."""
        try:
            return [p.model_dump(mode="json") for p in build_presets(story=story)]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/render")
    def render_file(req: RenderRequest) -> Response:
        rendered = render(req.invoice, req.format, settings.owner_name, settings.owner_address)
        if rendered is None:
            raise HTTPException(400, "the body format has no file to render")
        inline = req.format in ("pdf", "png")
        disposition = "inline" if inline else "attachment"
        return Response(
            rendered.data,
            media_type=rendered.content_type,
            headers={"Content-Disposition": f'{disposition}; filename="{rendered.filename}"'},
        )

    def _build(req: SendRequest) -> tuple[str, EmailMessage, Rendered | None, bytes]:
        msg, attachment = build_message(req, settings)
        raw = message_bytes(msg)
        built_id = store.new_id()
        store.put(built_id, raw)
        return built_id, msg, attachment, raw

    @app.post("/api/preview")
    def preview(req: SendRequest) -> dict:
        """Build without persisting: the UI calls this while the operator edits the form."""
        msg, attachment = build_message(req, settings)
        raw = message_bytes(msg)
        info = describe(msg, attachment, "preview", raw)
        return {**info.model_dump(), "intake_json_preview": _intake_preview(raw)}

    @app.post("/api/build")
    def build(req: SendRequest) -> dict:
        built_id, msg, attachment, raw = _build(req)
        info: BuiltMessage = describe(msg, attachment, built_id, raw)
        return {**info.model_dump(), "eml_url": f"/api/eml/{built_id}"}

    @app.post("/api/send")
    def send(req: SendRequest) -> SendLogEntry:
        built_id, msg, attachment, raw = _build(req)
        envelope_from = req.sender.envelope_from or req.sender.from_addr
        result = deliver(req.delivery, msg, raw, settings, envelope_from=envelope_from)
        if req.delivery == "none":
            status = "built"
        else:
            status = "sent" if result.ok else "failed"
        entry = SendLogEntry(
            id=built_id,
            at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            scenario=req.scenario,
            label=req.label,
            vendor_name=req.invoice.vendor_name,
            invoice_number=req.invoice.invoice_number,
            amount=req.invoice.amount,
            currency=req.invoice.currency,
            format=req.format,
            delivery=req.delivery,
            from_addr=req.sender.from_addr,
            reply_to=req.sender.reply_to,
            to=settings.mail_to,
            auth_summary=auth_summary(req.sender),
            status=status,
            detail=result.detail,
            message_id=str(msg["Message-ID"] or ""),
            attachment_name=attachment.filename if attachment else None,
            eml_url=f"/api/eml/{built_id}",
            receiver_message_id=result.receiver_message_id,
        )
        store.append(entry)
        return entry

    # The UI polls the receiver through these two proxies (same origin, no CORS or secrets in
    # the browser) to show "received → forwarded to backend" live next to each send.
    @app.get("/api/receiver/health")
    def receiver_health() -> dict:
        base = settings.receiver_api_base
        try:
            r = httpx.get(f"{base}/health", timeout=3.0)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            return {"reachable": False, "url": base, "error": str(exc)[:200]}
        return {"reachable": True, "url": base, "health": data}

    @app.get("/api/receiver/messages/{receiver_id}")
    def receiver_message(receiver_id: str) -> dict:
        if not RECEIVER_ID_RE.match(receiver_id):
            raise HTTPException(404, "not found")
        base = settings.receiver_api_base
        try:
            r = httpx.get(f"{base}/recent/{receiver_id}", timeout=3.0)
        except httpx.HTTPError as exc:
            return {"reachable": False, "error": str(exc)[:200]}
        if r.status_code == 404:
            return {"reachable": True, "found": False}
        try:
            r.raise_for_status()
            view = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            return {"reachable": False, "error": str(exc)[:200]}
        meta = view.get("meta") or {}
        return {
            "reachable": True,
            "found": True,
            "delivery": meta.get("delivery") or {},
            "attachments_kept": meta.get("attachments_kept"),
            "attachments_dropped": meta.get("attachments_dropped"),
            "warnings": meta.get("warnings") or [],
            "authentication_results": meta.get("authentication_results") or [],
        }

    @app.get("/api/eml/{built_id}")
    def eml(built_id: str) -> Response:
        if not built_id.replace("-", "").isalnum():
            raise HTTPException(404, "not found")
        raw = store.get(built_id)
        if raw is None:
            raise HTTPException(404, "not found")
        return Response(
            raw,
            media_type="message/rfc822",
            headers={"Content-Disposition": f'attachment; filename="vouch-demo-{built_id}.eml"'},
        )

    @app.get("/api/log")
    def log() -> list[SendLogEntry]:
        return list(reversed(store.log))[:200]

    @app.delete("/api/log")
    def clear_log() -> JSONResponse:
        store.clear()
        return JSONResponse({"ok": True})

    return app


def run(settings: Settings | None = None) -> None:
    import uvicorn

    settings = settings or load_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")


__all__ = ["create_app", "run", "Store"]
