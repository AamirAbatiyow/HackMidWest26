"""Stub of the Vouch backend intake endpoint — tests only.

Accepts ``POST /v1/intake/email`` as JSON (IntakeRequest shape) or ``message/rfc822``, checks
the shared-secret header when ``INTAKE_SHARED_SECRET`` is set, records every request to a
JSONL file and answers with a fake invoice card. ``FAIL_FIRST=N`` makes the first N requests
fail with HTTP 503 so retry/backoff can be exercised.

    python stub_backend.py --port 8101 --record /tmp/stub-intake.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
from datetime import UTC, datetime
from email import message_from_bytes, policy
from pathlib import Path

from aiohttp import web


def _eml_to_intake(raw: bytes) -> dict:
    msg = message_from_bytes(raw, policy=policy.default)
    headers = {k: "\n".join(str(v) for v in msg.get_all(k, [])) for k in msg.keys()}
    attachments, body_text = [], ""
    for part in msg.walk():
        if part.is_multipart():
            continue
        if part.get_filename() and part.get_content_type() not in ("text/plain", "text/html"):
            payload = part.get_payload(decode=True) or b""
            attachments.append(
                {
                    "filename": part.get_filename(),
                    "content_type": part.get_content_type(),
                    "data_b64": base64.b64encode(payload).decode(),
                    "size": len(payload),
                }
            )
        elif part.get_content_type() == "text/plain" and not body_text:
            body_text = part.get_content()
    return {
        "headers": headers,
        "body_text": body_text,
        "body_html": "",
        "attachments": attachments,
        "source": "email",
    }


def _summarize(intake: dict) -> dict:
    """A fake invoice card: enough for the e2e script to assert on."""
    text = intake.get("body_text", "")
    from_ = intake.get("headers", {}).get("From", "")
    m = re.search(
        r"Invoice (?:No:?\s*)?([A-Z]{2,3}-[0-9-]+)", intake.get("headers", {}).get("Subject", "") + " " + text
    )
    return {
        "id": "pay-" + datetime.now(UTC).strftime("%H%M%S%f"),
        "vendor_from": from_,
        "invoice_number_guess": m.group(1) if m else None,
        "attachments": [
            {"filename": a["filename"], "content_type": a["content_type"], "size": a.get("size")}
            for a in intake.get("attachments", [])
        ],
        "authentication_results": intake.get("headers", {}).get("Authentication-Results"),
        "status": "received-by-stub",
    }


def build_app(record_path: Path, secret: str, fail_first: int) -> web.Application:
    app = web.Application(client_max_size=64 * 1024 * 1024)
    state = {"n": 0, "failures_left": fail_first}

    async def intake(request: web.Request) -> web.Response:
        state["n"] += 1
        presented = request.headers.get(os.environ.get("INTAKE_SECRET_HEADER", "X-Vouch-Intake-Secret"), "")
        if secret and presented != secret:
            return web.json_response({"error": "bad or missing shared secret"}, status=401)
        if state["failures_left"] > 0:
            state["failures_left"] -= 1
            return web.json_response({"error": "simulated outage"}, status=503)
        raw = await request.read()
        if request.content_type == "message/rfc822":
            intake_body, mode = _eml_to_intake(raw), "eml"
        else:
            try:
                intake_body, mode = json.loads(raw), "json"
            except json.JSONDecodeError:
                return web.json_response({"error": "body is neither JSON nor message/rfc822"}, status=400)
        card = _summarize(intake_body)
        record = {
            "n": state["n"],
            "at": datetime.now(UTC).isoformat(),
            "mode": mode,
            "path": request.path,
            "request_headers": {k: v for k, v in request.headers.items() if k.lower().startswith("x-vouch")},
            "intake": {
                **intake_body,
                "attachments": [
                    {**a, "data_b64": f"<{len(a.get('data_b64', ''))} b64 chars>"}
                    for a in intake_body.get("attachments", [])
                ],
            },
            "card": card,
        }
        with record_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        return web.json_response({"cards": [card]}, status=200)

    async def health(_r: web.Request) -> web.Response:
        return web.json_response(
            {"ok": True, "requests": state["n"], "failures_left": state["failures_left"]}
        )

    app.add_routes(
        [
            web.post("/v1/intake/email", intake),
            web.post("/v1/intake/upload", intake),
            web.get("/health", health),
        ]
    )
    return app


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8101)
    ap.add_argument("--record", default="/tmp/stub-intake.jsonl")
    ap.add_argument("--fail-first", type=int, default=int(os.environ.get("FAIL_FIRST", "0")))
    args = ap.parse_args()
    record = Path(args.record)
    record.parent.mkdir(parents=True, exist_ok=True)
    secret = os.environ.get("INTAKE_SHARED_SECRET", "")
    runner = web.AppRunner(build_app(record, secret, args.fail_first), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, args.host, args.port).start()
    print(
        f"stub backend listening on http://{args.host}:{args.port}/v1/intake/email → {record} "
        f"(secret {'on' if secret else 'off'}, fail_first={args.fail_first})",
        flush=True,
    )
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
