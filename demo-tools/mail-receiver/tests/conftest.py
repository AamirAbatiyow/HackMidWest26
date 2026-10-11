"""Shared fixtures: an in-process stub backend, a Receiver with SMTP + HTTP on ephemeral ports."""

from __future__ import annotations

import asyncio
import json
import smtplib
from email.message import EmailMessage
from pathlib import Path

import pytest
from aiohttp import web

from mail_receiver.config import Settings
from mail_receiver.http_api import build_app
from mail_receiver.pipeline import Receiver
from mail_receiver.smtp_handler import smtp_factory

PDF = b"%PDF-1.4\n%demo\n" + b"0" * 64


class StubBackend:
    """Records every intake POST; can fail the first N requests with 503."""

    def __init__(self, fail_first: int = 0, secret: str = "") -> None:
        self.fail_first = fail_first
        self.secret = secret
        self.requests: list[dict] = []
        self.runner: web.AppRunner | None = None
        self.url = ""

    async def start(self) -> StubBackend:
        app = web.Application(client_max_size=64 * 1024 * 1024)

        async def intake(request: web.Request) -> web.Response:
            headers = dict(request.headers)
            if self.secret and headers.get("X-Vouch-Intake-Secret") != self.secret:
                return web.json_response({"error": "unauthorized"}, status=401)
            if self.fail_first > 0:
                self.fail_first -= 1
                return web.json_response({"error": "outage"}, status=503)
            if request.content_type == "multipart/form-data":
                # the real backend's /v1/intake/eml: multipart with a ``file`` field + submitted_by
                form = await request.post()
                field = form["file"]
                body = {
                    "file_len": len(field.file.read()),
                    "filename": field.filename,
                    "file_content_type": field.content_type,
                    "submitted_by": form.get("submitted_by"),
                }
            else:
                raw = await request.read()
                body = (
                    json.loads(raw) if request.content_type == "application/json" else {"raw_len": len(raw)}
                )
            self.requests.append({"headers": headers, "body": body, "content_type": request.content_type})
            return web.json_response({"cards": [{"id": f"pay-{len(self.requests)}"}]})

        app.add_routes([web.post("/v1/intake", intake), web.post("/v1/intake/eml", intake)])
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = self.runner.addresses[0][1]
        self.url = f"http://127.0.0.1:{port}/v1/intake"
        self.eml_url = f"http://127.0.0.1:{port}/v1/intake/eml"
        return self

    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()


class RunningReceiver:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.receiver = Receiver(settings)
        self.smtp_server: asyncio.AbstractServer | None = None
        self.smtp_port = 0
        self.http_runner: web.AppRunner | None = None
        self.http_url = ""

    async def start(self) -> RunningReceiver:
        await self.receiver.start()
        loop = asyncio.get_running_loop()
        self.smtp_server = await loop.create_server(smtp_factory(self.receiver, 0), "127.0.0.1", 0)
        self.smtp_port = self.smtp_server.sockets[0].getsockname()[1]
        self.http_runner = web.AppRunner(build_app(self.receiver), access_log=None)
        await self.http_runner.setup()
        site = web.TCPSite(self.http_runner, "127.0.0.1", 0)
        await site.start()
        self.http_url = f"http://127.0.0.1:{self.http_runner.addresses[0][1]}"
        return self

    async def stop(self) -> None:
        if self.smtp_server:
            self.smtp_server.close()
            await self.smtp_server.wait_closed()
        if self.http_runner:
            await self.http_runner.cleanup()
        await self.receiver.stop()

    async def send(self, msg: EmailMessage, *, mail_from: str | None = None, rcpt: str | None = None) -> dict:
        """Deliver over real SMTP from a worker thread (smtplib is blocking)."""

        def _send() -> dict:
            with smtplib.SMTP("127.0.0.1", self.smtp_port, timeout=10) as s:
                return s.send_message(msg, from_addr=mail_from, to_addrs=[rcpt] if rcpt else None)

        return await asyncio.to_thread(_send)

    async def wait_for_delivery(self, msg_id: str, timeout: float = 10.0) -> dict:
        """Poll meta.json until the delivery leaves the queued/retrying states."""
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            meta = self.receiver.store.load_meta(msg_id) or {}
            status = meta.get("delivery", {}).get("status")
            if status in ("delivered", "dead_letter", "stored"):
                return meta
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError(f"delivery of {msg_id} still {status!r} after {timeout}s")
            await asyncio.sleep(0.05)


def make_settings(tmp_path: Path, **overrides) -> Settings:
    s = Settings(data_dir=tmp_path / "data", smtp_ports=(0,), http_port=0)
    s.delivery_backoff_base_s = 0.02
    s.delivery_backoff_max_s = 0.1
    s.delivery_max_attempts = 3
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def demo_message(subject: str = "Invoice RP-10517", attach_pdf: bool = True) -> EmailMessage:
    msg = EmailMessage()
    msg["Received"] = (
        "from mail.reyespackaging.mx ([203.0.113.10]) by mx.vouch.local (demo-simulated hop) with ESMTPS id x"
    )
    msg["Authentication-Results"] = (
        "mx.vouch.local (demo-simulated); spf=pass smtp.mailfrom=reyespackaging.mx; "
        "dkim=pass header.d=reyespackaging.mx; dmarc=pass header.from=reyespackaging.mx"
    )
    msg["From"] = "Reyes Packaging AR <ar@reyespackaging.mx>"
    msg["To"] = "business@vouch.local"
    msg["Subject"] = subject
    msg["X-Vouch-Demo"] = "synthetic"
    msg.set_content("Hola, attached is invoice RP-10517.\n")
    if attach_pdf:
        msg.add_attachment(PDF, maintype="application", subtype="pdf", filename="RP-10517.pdf")
    return msg


@pytest.fixture
async def stub_backend():
    stub = await StubBackend(secret="s3cret").start()
    yield stub
    await stub.stop()


@pytest.fixture
async def running(tmp_path, stub_backend):
    settings = make_settings(tmp_path, backend_intake_url=stub_backend.url, intake_shared_secret="s3cret")
    rr = await RunningReceiver(settings).start()
    yield rr
    await rr.stop()
