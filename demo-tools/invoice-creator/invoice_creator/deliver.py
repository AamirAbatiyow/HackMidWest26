"""Deliver a built message: direct SMTP to the receiver, or HTTP fallbacks when SMTP is blocked."""

from __future__ import annotations

import re
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

import httpx

from .config import Settings
from .mail import eml_to_intake_json


@dataclass
class DeliveryResult:
    ok: bool
    detail: str
    receiver_message_id: str = ""  # the receiver's id for this message, when it told us

    @staticmethod
    def id_from_smtp_reply(reply: bytes | str) -> str:
        """The receiver answers DATA with ``250 OK: queued as <id>``."""
        text = reply.decode("ascii", "replace") if isinstance(reply, bytes) else reply
        m = _QUEUED_AS.search(text)
        return m.group(1) if m else ""


_QUEUED_AS = re.compile(r"queued as (\S+)")


def send_smtp(
    msg: EmailMessage, settings: Settings, *, envelope_from: str, to: str | None = None
) -> DeliveryResult:
    """One SMTP transaction, command by command, so we keep the server's final reply
    (``smtplib.send_message`` discards it, and it carries the receiver's message id)."""
    to = to or settings.mail_to
    raw = msg.as_bytes(policy=msg.policy.clone(linesep="\r\n"))
    where = f"{settings.smtp_host}:{settings.smtp_port}"
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_s) as smtp:
            smtp.ehlo_or_helo_if_needed()
            code, reply = smtp.mail(envelope_from)
            if code != 250:
                return DeliveryResult(False, f"MAIL FROM refused: {code} {reply.decode(errors='replace')}")
            code, reply = smtp.rcpt(to)
            if code not in (250, 251):
                return DeliveryResult(
                    False, f"recipient {to} refused: {code} {reply.decode(errors='replace')}"
                )
            code, reply = smtp.data(raw)
            if code != 250:
                return DeliveryResult(False, f"DATA refused: {code} {reply.decode(errors='replace')}")
        return DeliveryResult(
            True,
            f"accepted by {where} for {to}",
            receiver_message_id=DeliveryResult.id_from_smtp_reply(reply),
        )
    except smtplib.SMTPResponseException as exc:
        return DeliveryResult(False, f"SMTP {exc.smtp_code}: {exc.smtp_error!r}")
    except (smtplib.SMTPException, OSError) as exc:
        return DeliveryResult(False, f"SMTP connection to {where} failed: {exc}")


def _secret_headers(settings: Settings) -> dict[str, str]:
    return (
        {settings.intake_secret_header: settings.intake_shared_secret}
        if settings.intake_shared_secret
        else {}
    )


def post_eml(
    url: str, raw: bytes, settings: Settings, *, extra: dict[str, str] | None = None
) -> DeliveryResult:
    headers = {
        "Content-Type": "message/rfc822",
        "X-Vouch-Demo": "invoice-creator",
        **_secret_headers(settings),
    }
    headers.update(extra or {})
    try:
        r = httpx.post(url, content=raw, headers=headers, timeout=settings.http_timeout_s)
    except httpx.HTTPError as exc:
        return DeliveryResult(False, f"POST {url} failed: {exc}")
    body = r.text[:300].replace("\n", " ")
    return DeliveryResult(
        r.is_success,
        f"POST {url} → HTTP {r.status_code} {body}".strip(),
        receiver_message_id=_receiver_id_from_response(r),
    )


def _receiver_id_from_response(r: httpx.Response) -> str:
    """The receiver's /inbound answers ``{"id": "...", "queued": true}``."""
    try:
        data = r.json()
    except ValueError:
        return ""
    if isinstance(data, dict) and data.get("queued") and isinstance(data.get("id"), str):
        return data["id"]
    return ""


def post_json(url: str, payload: dict, settings: Settings) -> DeliveryResult:
    headers = {"X-Vouch-Demo": "invoice-creator", **_secret_headers(settings)}
    try:
        r = httpx.post(url, json=payload, headers=headers, timeout=settings.http_timeout_s)
    except httpx.HTTPError as exc:
        return DeliveryResult(False, f"POST {url} failed: {exc}")
    body = r.text[:300].replace("\n", " ")
    return DeliveryResult(r.is_success, f"POST {url} → HTTP {r.status_code} {body}".strip())


def deliver(
    delivery: str, msg: EmailMessage, raw: bytes, settings: Settings, *, envelope_from: str
) -> DeliveryResult:
    if delivery == "none":
        return DeliveryResult(True, "built only; not delivered")
    if delivery == "smtp":
        return send_smtp(msg, settings, envelope_from=envelope_from)
    if delivery == "receiver_http":
        if not settings.receiver_inbound_url:
            return DeliveryResult(False, "RECEIVER_INBOUND_URL is not configured")
        return post_eml(
            settings.receiver_inbound_url,
            raw,
            settings,
            extra={"X-Vouch-Envelope-From": envelope_from, "X-Vouch-Rcpt-To": settings.mail_to},
        )
    if delivery == "backend":
        if not settings.backend_intake_url:
            return DeliveryResult(False, "BACKEND_INTAKE_URL is not configured")
        if settings.backend_intake_format == "json":
            return post_json(settings.backend_intake_url, eml_to_intake_json(raw), settings)
        return post_eml(settings.backend_intake_url, raw, settings)
    return DeliveryResult(False, f"unknown delivery {delivery!r}")
