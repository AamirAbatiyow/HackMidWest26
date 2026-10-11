"""Small aiohttp API: /health, /recent (metadata only), /inbound (HTTP fallback when SMTP is
blocked) and /dead-letter/retry."""

from __future__ import annotations

import hmac
import logging
import re

from aiohttp import web

from . import __version__
from .pipeline import Receiver

log = logging.getLogger(__name__)

MAX_INBOUND_BYTES_MARGIN = 1024 * 1024  # headroom over the SMTP limit for HTTP framing
MSG_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{12}-[0-9a-f]{6}$")

# The read-only, metadata-only endpoints are meant to be shown on a demo page served from
# another origin (the invoice creator), so they answer cross-origin GETs.
READ_ONLY_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Cache-Control": "no-store",
}


def _authorized(request: web.Request, receiver: Receiver) -> bool:
    secret = receiver.settings.intake_shared_secret
    if not secret:
        return True  # no secret configured: open (documented; use the firewall)
    presented = request.headers.get(receiver.settings.intake_secret_header, "")
    return hmac.compare_digest(presented, secret)


def _json(data, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, headers=READ_ONLY_CORS)


def build_app(receiver: Receiver) -> web.Application:
    app = web.Application(client_max_size=receiver.settings.max_message_bytes + MAX_INBOUND_BYTES_MARGIN)

    async def index(_request: web.Request) -> web.Response:
        s = receiver.settings
        accepting = ", ".join(sorted(s.accepted_addresses)) if not s.accept_any_recipient else "* (any)"
        text = (
            f"Vouch mail receiver {__version__}\n"
            f"accepting mail for: {accepting}\n"
            f"SMTP ports: {', '.join(map(str, s.smtp_ports))}\n"
            "endpoints: GET /health · GET /recent · GET /recent/{id} · "
            "POST /inbound (message/rfc822) · POST /dead-letter/retry\n"
        )
        return web.Response(text=text)

    async def health(_request: web.Request) -> web.Response:
        return _json({"version": __version__, **receiver.health()})

    async def recent(_request: web.Request) -> web.Response:
        return _json({"count": len(receiver.recent()), "messages": receiver.recent()})

    async def recent_one(request: web.Request) -> web.Response:
        msg_id = request.match_info["msg_id"]
        if not MSG_ID_RE.match(msg_id):
            return _json({"error": "not found"}, status=404)
        view = receiver.message_view(msg_id)
        if view is None:
            return _json({"error": "not found"}, status=404)
        return _json(view)

    async def cors_preflight(_request: web.Request) -> web.Response:
        return web.Response(status=204, headers=READ_ONLY_CORS)

    async def inbound(request: web.Request) -> web.Response:
        if not _authorized(request, receiver):
            return web.json_response({"error": "unauthorized"}, status=401)
        ctype = request.content_type
        if ctype not in ("message/rfc822", "application/octet-stream", "text/plain"):
            return web.json_response(
                {"error": f"unsupported content type {ctype!r}; send message/rfc822"}, status=415
            )
        raw = await request.read()
        if not raw.strip():
            return web.json_response({"error": "empty body"}, status=400)
        if len(raw) > receiver.settings.max_message_bytes:
            return web.json_response({"error": "message too large"}, status=413)
        rcpt = request.headers.get("X-Vouch-Rcpt-To", "")
        if rcpt and not receiver.settings.accepts(rcpt):
            return web.json_response({"error": f"recipient {rcpt} not accepted"}, status=550)
        peer = request.remote or ""
        msg_id = await receiver.ingest(
            raw,
            via="http:inbound",
            envelope_from=request.headers.get("X-Vouch-Envelope-From", ""),
            rcpt_tos=[rcpt] if rcpt else sorted(receiver.settings.accepted_addresses),
            peer=peer,
            helo=request.headers.get("User-Agent", ""),
        )
        return web.json_response({"id": msg_id, "queued": True}, status=202)

    async def retry_dead_letters(request: web.Request) -> web.Response:
        if not _authorized(request, receiver):
            return web.json_response({"error": "unauthorized"}, status=401)
        n = await receiver.worker.requeue_dead_letters()
        return web.json_response({"requeued": n})

    app.add_routes(
        [
            web.get("/", index),
            web.get("/health", health),
            web.get("/recent", recent),
            web.get("/recent/{msg_id}", recent_one),
            web.options("/health", cors_preflight),
            web.options("/recent", cors_preflight),
            web.options("/recent/{msg_id}", cors_preflight),
            web.post("/inbound", inbound),
            web.post("/dead-letter/retry", retry_dead_letters),
        ]
    )
    return app


async def start_http(receiver: Receiver) -> web.AppRunner:
    app = build_app(receiver)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, receiver.settings.http_host, receiver.settings.http_port)
    await site.start()
    log.info("HTTP listening on %s:%d", receiver.settings.http_host, receiver.settings.http_port)
    return runner
