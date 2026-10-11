"""End-to-end over real SMTP: acceptance, rejection, storage, forwarding, retries, HTTP API."""

from __future__ import annotations

import json
import smtplib

import aiohttp
import pytest

from tests.conftest import PDF, RunningReceiver, StubBackend, demo_message, make_settings


async def _recent(rr: RunningReceiver) -> list[dict]:
    async with aiohttp.ClientSession() as http, http.get(f"{rr.http_url}/recent") as r:
        return (await r.json())["messages"]


async def _health(rr: RunningReceiver) -> dict:
    async with aiohttp.ClientSession() as http, http.get(f"{rr.http_url}/health") as r:
        return await r.json()


async def test_accepts_stores_and_forwards(running: RunningReceiver, stub_backend: StubBackend):
    refused = await running.send(demo_message())
    assert refused == {}
    (meta,) = await _recent(running)
    msg_id = meta["id"]
    meta = await running.wait_for_delivery(msg_id)
    assert meta["delivery"]["status"] == "delivered"
    assert meta["delivery"]["attempts"] == 1

    # on disk: raw message byte-for-byte, intake json, meta, attachment with safe mode
    d = running.receiver.store.dir_for(msg_id)
    raw = (d / "message.eml").read_bytes()
    assert b"Authentication-Results: mx.vouch.local (demo-simulated)" in raw
    assert (d / "attachments" / "RP-10517.pdf").read_bytes() == PDF
    assert oct((d / "attachments" / "RP-10517.pdf").stat().st_mode & 0o777) == "0o640"
    intake = json.loads((d / "intake.json").read_text())
    assert intake["headers"]["From"] == "Reyes Packaging AR <ar@reyespackaging.mx>"
    assert intake["headers"]["Received"].startswith("from mail.reyespackaging.mx")
    assert intake["attachments"][0]["filename"] == "RP-10517.pdf"

    # what the backend got
    (req,) = stub_backend.requests
    assert req["headers"]["X-Vouch-Intake-Secret"] == "s3cret"
    assert req["headers"]["X-Vouch-Receiver-Message-Id"] == msg_id
    assert req["headers"]["X-Vouch-Envelope-From"] == "ar@reyespackaging.mx"
    assert req["content_type"] == "application/json"
    body = req["body"]
    assert body["source"] == "email"
    assert body["headers"]["Authentication-Results"] == intake["headers"]["Authentication-Results"]
    assert body["attachments"][0]["sha256"] == intake["attachments"][0]["sha256"]
    assert body["body_text"].startswith("Hola")

    # metadata only on /recent, envelope captured
    assert meta["via"].startswith("smtp:")
    assert meta["envelope_from"] == "ar@reyespackaging.mx"
    assert meta["rcpt_tos"] == ["business@vouch.local"]
    assert meta["authentication_results"][0].startswith("mx.vouch.local (demo-simulated)")
    assert meta["received_headers"][0].startswith("from mail.reyespackaging.mx")
    assert "body_text" not in meta and "data_b64" not in json.dumps(meta)

    health = await _health(running)
    assert health["status"] == "ok"
    assert health["received_total"] == 1
    assert health["delivered_total"] == 1
    assert health["queue_depth"] == 0
    assert health["last_delivery"]["ok"] is True
    assert health["config"]["accepting"] == ["business@vouch.local"]


async def test_rejects_other_recipients(running: RunningReceiver):
    with pytest.raises(smtplib.SMTPRecipientsRefused) as exc:
        await running.send(demo_message(), rcpt="someone@else.test")
    assert exc.value.recipients["someone@else.test"][0] == 550
    assert (await _health(running))["rejected_recipients_total"] == 1
    assert await _recent(running) == []


async def test_recipient_match_is_case_insensitive_and_domain_bound(tmp_path):
    s = make_settings(tmp_path, mail_domain="Example.ORG", accept_local_parts=("business", "ap"))
    assert s.accepts("Business@example.org")
    assert s.accepts("<ap@EXAMPLE.org>")
    assert not s.accepts("business@vouch.local")
    assert not s.accepts("ceo@example.org")
    s.accept_any_recipient = True
    assert s.accepts("anyone@anywhere.test")


async def test_message_size_limit(tmp_path, stub_backend: StubBackend):
    settings = make_settings(tmp_path, max_message_bytes=4000, backend_intake_url=stub_backend.url)
    rr = await RunningReceiver(settings).start()
    try:
        msg = demo_message()
        msg.add_attachment(PDF + b"A" * 8000, maintype="application", subtype="pdf", filename="big.pdf")
        with pytest.raises(smtplib.SMTPSenderRefused) as exc:
            await rr.send(msg)
        assert exc.value.smtp_code == 552
        assert await _recent(rr) == []
    finally:
        await rr.stop()


async def test_disallowed_attachments_are_dropped_but_message_forwarded(
    running: RunningReceiver, stub_backend: StubBackend
):
    msg = demo_message(attach_pdf=False)
    msg.add_attachment(b"MZ\x90\x00", maintype="application", subtype="octet-stream", filename="payload.exe")
    msg.add_attachment(b"a,b\n1,2\n", maintype="text", subtype="csv", filename="ok.csv")
    await running.send(msg)
    (meta,) = await _recent(running)
    await running.wait_for_delivery(meta["id"])
    verdict = {a["filename"]: a["kept"] for a in meta["attachments"]}
    assert verdict == {"payload.exe": False, "ok.csv": True}
    assert meta["attachments_dropped"] == 1
    (req,) = stub_backend.requests
    assert [a["filename"] for a in req["body"]["attachments"]] == ["ok.csv"]


async def test_retries_with_backoff_then_delivers(tmp_path):
    stub = await StubBackend(fail_first=2).start()
    try:
        rr = await RunningReceiver(make_settings(tmp_path, backend_intake_url=stub.url)).start()
        try:
            await rr.send(demo_message())
            (meta,) = await _recent(rr)
            meta = await rr.wait_for_delivery(meta["id"])
            assert meta["delivery"]["status"] == "delivered"
            assert meta["delivery"]["attempts"] == 3
            assert len(stub.requests) == 1
            assert rr.receiver.store.dead_letter_count() == 0
        finally:
            await rr.stop()
    finally:
        await stub.stop()


async def test_dead_letter_after_max_attempts_and_requeue(tmp_path):
    stub = await StubBackend(fail_first=10**6).start()
    try:
        rr = await RunningReceiver(make_settings(tmp_path, backend_intake_url=stub.url)).start()
        try:
            await rr.send(demo_message())
            (meta,) = await _recent(rr)
            msg_id = meta["id"]
            meta = await rr.wait_for_delivery(msg_id)
            assert meta["delivery"]["status"] == "dead_letter"
            assert meta["delivery"]["attempts"] == 3
            dead = rr.receiver.store.dead / f"{msg_id}.json"
            assert dead.exists()
            record = json.loads(dead.read_text())
            assert record["attempts"] == 3 and "HTTP 503" in record["error"]
            health = await _health(rr)
            assert health["status"] == "degraded" and health["dead_letter_count"] == 1
            assert health["last_delivery"]["ok"] is False

            # backend comes back: requeue via the API
            stub.fail_first = 0
            async with aiohttp.ClientSession() as http, http.post(f"{rr.http_url}/dead-letter/retry") as r:
                assert r.status == 200 and (await r.json()) == {"requeued": 1}
            meta = await rr.wait_for_delivery(msg_id)
            assert meta["delivery"]["status"] == "delivered"
            assert not dead.exists()
            assert (await _health(rr))["status"] == "ok"
        finally:
            await rr.stop()
    finally:
        await stub.stop()


async def test_store_only_when_no_backend_configured(tmp_path):
    rr = await RunningReceiver(make_settings(tmp_path, backend_intake_url="")).start()
    try:
        await rr.send(demo_message())
        (meta,) = await _recent(rr)
        meta = await rr.wait_for_delivery(meta["id"])
        assert meta["delivery"]["status"] == "stored"
        assert (await _health(rr))["status"] == "store-only"
    finally:
        await rr.stop()


async def test_eml_forwarding_format(tmp_path):
    stub = await StubBackend().start()
    try:
        settings = make_settings(tmp_path, backend_intake_url=stub.url, backend_intake_format="eml")
        rr = await RunningReceiver(settings).start()
        try:
            await rr.send(demo_message())
            (meta,) = await _recent(rr)
            await rr.wait_for_delivery(meta["id"])
            (req,) = stub.requests
            assert req["content_type"] == "message/rfc822"
            assert req["body"]["raw_len"] == meta["size"]
        finally:
            await rr.stop()
    finally:
        await stub.stop()


async def test_http_inbound_fallback(running: RunningReceiver, stub_backend: StubBackend):
    raw = demo_message(subject="Invoice via HTTP").as_bytes()
    async with aiohttp.ClientSession() as http:
        async with http.post(f"{running.http_url}/inbound", data=raw, headers={"Content-Type": "message/rfc822"}) as r:
            assert r.status == 401  # secret required
        headers = {"Content-Type": "message/rfc822", "X-Vouch-Intake-Secret": "s3cret", "X-Vouch-Rcpt-To": "x@y.test"}
        async with http.post(f"{running.http_url}/inbound", data=raw, headers=headers) as r:
            assert r.status == 550
        headers["X-Vouch-Rcpt-To"] = "business@vouch.local"
        headers["X-Vouch-Envelope-From"] = "ar@reyespackaging.mx"
        async with http.post(f"{running.http_url}/inbound", data=raw, headers=headers) as r:
            assert r.status == 202
            msg_id = (await r.json())["id"]
        async with http.post(f"{running.http_url}/inbound", data=b"", headers=headers) as r:
            assert r.status == 400
        async with http.post(f"{running.http_url}/inbound", json={"x": 1}, headers={"X-Vouch-Intake-Secret": "s3cret"}) as r:
            assert r.status == 415
    meta = await running.wait_for_delivery(msg_id)
    assert meta["via"] == "http:inbound"
    assert meta["envelope_from"] == "ar@reyespackaging.mx"
    assert meta["subject"] == "Invoice via HTTP"
    assert meta["delivery"]["status"] == "delivered"
    assert stub_backend.requests[-1]["body"]["headers"]["Subject"] == "Invoice via HTTP"


async def test_recent_is_bounded_and_newest_first(tmp_path, stub_backend: StubBackend):
    settings = make_settings(tmp_path, backend_intake_url=stub_backend.url, intake_shared_secret="s3cret", recent_limit=3)
    rr = await RunningReceiver(settings).start()
    try:
        for i in range(5):
            await rr.send(demo_message(subject=f"Invoice {i}"))
        recent = await _recent(rr)
        assert [m["subject"] for m in recent] == ["Invoice 4", "Invoice 3", "Invoice 2"]
        assert (await _health(rr))["received_total"] == 5
    finally:
        await rr.stop()
