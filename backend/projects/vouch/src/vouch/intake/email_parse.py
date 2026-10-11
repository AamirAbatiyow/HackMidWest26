"""Email intake: raw RFC-822 (.eml) or a JSON envelope → headers, body and attachments."""

from __future__ import annotations

import base64
import hashlib
import re
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr

from ..contracts import Attachment, EmailEnvelope, IntakeRequest


def _addr(value: str | None) -> tuple[str, str]:
    if not value:
        return "", ""
    name, addr = parseaddr(value)
    return name.strip(), addr.strip().lower()


def _header_list(msg: EmailMessage, name: str) -> list[str]:
    return [str(v) for v in msg.get_all(name, [])]


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>|</h\d>", "\n", text)
    text = re.sub(r"(?i)</t[dh]>", "\t", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def envelope_from_headers(headers: dict[str, str]) -> EmailEnvelope:
    lower = {k.lower(): v for k, v in headers.items()}
    from_name, from_addr = _addr(lower.get("from"))
    _, reply_to = _addr(lower.get("reply-to"))
    auth = [
        v.strip()
        for v in re.split(r"\n(?=Authentication-Results)", lower.get("authentication-results", ""))
        if v
    ]
    return EmailEnvelope(
        from_addr=from_addr,
        from_name=from_name,
        reply_to=reply_to,
        to=lower.get("to", ""),
        subject=lower.get("subject", ""),
        date=lower.get("date", ""),
        message_id=lower.get("message-id", ""),
        authentication_results=auth,
        received_spf=lower.get("received-spf", ""),
        headers={k: v for k, v in headers.items()},
    )


def parse_eml(raw: bytes) -> IntakeRequest:
    """Parse a raw .eml into an IntakeRequest (headers, text body, attachments)."""
    msg = message_from_bytes(raw, policy=policy.default)
    headers: dict[str, str] = {}
    for key in msg.keys():
        values = _header_list(msg, key)
        headers[key] = "\n".join(values) if len(values) > 1 else values[0]
    body_text, body_html = "", ""
    attachments: list[Attachment] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        ctype = part.get_content_type()
        filename = part.get_filename()
        if disposition == "attachment" or (filename and ctype not in ("text/plain", "text/html")):
            payload = part.get_payload(decode=True) or b""
            attachments.append(
                Attachment(
                    filename=filename or "attachment",
                    content_type=ctype,
                    data_b64=base64.b64encode(payload).decode(),
                    sha256=sha256_hex(payload),
                    size=len(payload),
                )
            )
        elif ctype == "text/plain" and not body_text:
            body_text = part.get_content()
        elif ctype == "text/html" and not body_html:
            body_html = part.get_content()
    _, to_addrs = zip(*getaddresses(_header_list(msg, "To")), strict=False) if msg.get_all("To") else ((), ())
    if to_addrs and "To" not in headers:
        headers["To"] = ", ".join(to_addrs)
    return IntakeRequest(headers=headers, body_text=body_text, body_html=body_html, attachments=attachments)


def intake_body_text(req: IntakeRequest) -> str:
    if req.body_text.strip():
        return req.body_text
    if req.body_html.strip():
        return html_to_text(req.body_html)
    return ""
