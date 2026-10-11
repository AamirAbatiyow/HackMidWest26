"""Parse a raw RFC 5322 message into the Vouch backend's ``IntakeRequest`` shape.

* Headers are captured verbatim (``Authentication-Results`` and ``Received`` included, in order;
  repeated headers are joined with newlines, exactly as the backend's own ``parse_eml`` does).
* Attachments are allow-listed by extension *and* by content sniffing. Nothing is executed,
  rendered, unzipped or interpreted: bytes are read, hashed, base64-encoded and stored.
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import message_from_bytes, policy
from email.utils import parseaddr

from .config import DEFAULT_ALLOWED_EXTENSIONS

# Canonical content types per allowed extension (declared MIME types are not trusted).
CANONICAL_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "txt": "text/plain",
}

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class AttachmentInfo:
    filename: str
    declared_type: str
    content_type: str
    size: int
    sha256: str
    kept: bool
    reason: str = ""

    def meta(self) -> dict:
        return {
            "filename": self.filename,
            "declared_type": self.declared_type,
            "content_type": self.content_type,
            "size": self.size,
            "sha256": self.sha256,
            "kept": self.kept,
            "reason": self.reason,
        }


@dataclass
class ParsedMail:
    intake: dict  # IntakeRequest body for the backend
    from_addr: str = ""
    from_name: str = ""
    reply_to: str = ""
    to: str = ""
    subject: str = ""
    date: str = ""
    message_id: str = ""
    authentication_results: list[str] = field(default_factory=list)  # raw, untouched
    received: list[str] = field(default_factory=list)  # raw, untouched
    attachments: list[AttachmentInfo] = field(default_factory=list)
    kept_payloads: dict[str, bytes] = field(default_factory=dict)  # safe filename → bytes
    warnings: list[str] = field(default_factory=list)

    @property
    def dropped(self) -> list[AttachmentInfo]:
        return [a for a in self.attachments if not a.kept]


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_filename(name: str, fallback: str = "attachment") -> str:
    """A filename safe to write under the storage directory (no paths, no control chars)."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    base = _SAFE_NAME_RE.sub("-", base).strip("-.")
    if not base or base in (".", ".."):
        base = fallback
    return base[:120]


def extension_of(filename: str) -> str:
    name = (filename or "").lower()
    return name.rsplit(".", 1)[-1] if "." in name else ""


def sniff_matches(ext: str, data: bytes) -> bool:
    """Does the payload look like what its extension claims? Conservative magic-byte checks."""
    head = data[:8]
    if ext == "pdf":
        return head.startswith(b"%PDF")
    if ext == "png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in ("jpg", "jpeg"):
        return head[:3] == b"\xff\xd8\xff"
    if ext == "xlsx":
        return head.startswith(b"PK\x03\x04")
    if ext in ("csv", "txt"):
        if b"\x00" in data:
            return False
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                data.decode("latin-1")
            except UnicodeDecodeError:
                return False
        return True
    return False


def check_attachment(
    filename: str,
    declared_type: str,
    data: bytes,
    *,
    allowed_extensions: tuple[str, ...] = DEFAULT_ALLOWED_EXTENSIONS,
    max_attachment_bytes: int = 10 * 1024 * 1024,
) -> AttachmentInfo:
    ext = extension_of(filename)
    info = AttachmentInfo(
        filename=filename or "attachment",
        declared_type=declared_type,
        content_type=CANONICAL_TYPES.get(ext, declared_type or "application/octet-stream"),
        size=len(data),
        sha256=sha256_hex(data),
        kept=False,
    )
    if ext not in allowed_extensions:
        info.reason = f"extension .{ext or '?'} not in allowlist"
    elif len(data) == 0:
        info.reason = "empty attachment"
    elif len(data) > max_attachment_bytes:
        info.reason = f"attachment larger than {max_attachment_bytes} bytes"
    elif not sniff_matches(ext, data):
        info.reason = f"content does not look like .{ext}"
    else:
        info.kept = True
    return info


def _header_values(msg, name: str) -> list[str]:
    return [str(v) for v in msg.get_all(name, [])]


def parse_message(
    raw: bytes,
    *,
    allowed_extensions: tuple[str, ...] = DEFAULT_ALLOWED_EXTENSIONS,
    max_attachment_bytes: int = 10 * 1024 * 1024,
    max_attachments: int = 10,
    received_at: datetime | None = None,
) -> ParsedMail:
    msg = message_from_bytes(raw, policy=policy.default)
    headers: dict[str, str] = {}
    for key in msg.keys():
        if key in headers:
            continue
        values = _header_values(msg, key)
        headers[key] = "\n".join(values) if len(values) > 1 else values[0]

    from_name, from_addr = parseaddr(str(msg.get("From", "")))
    _, reply_to = parseaddr(str(msg.get("Reply-To", "")))
    parsed = ParsedMail(
        intake={},
        from_addr=from_addr.lower(),
        from_name=from_name,
        reply_to=reply_to.lower(),
        to=str(msg.get("To", "")),
        subject=str(msg.get("Subject", "")),
        date=str(msg.get("Date", "")),
        message_id=str(msg.get("Message-ID", "")),
        authentication_results=_header_values(msg, "Authentication-Results"),
        received=_header_values(msg, "Received"),
    )

    body_text, body_html = "", ""
    attachments: list[dict] = []
    seen_names: set[str] = set()
    for part in msg.walk():
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        ctype = part.get_content_type()
        filename = part.get_filename()
        is_attachment = disposition == "attachment" or (filename and ctype not in ("text/plain", "text/html"))
        if is_attachment:
            payload = part.get_payload(decode=True) or b""
            info = check_attachment(
                filename or "attachment",
                ctype,
                payload,
                allowed_extensions=allowed_extensions,
                max_attachment_bytes=max_attachment_bytes,
            )
            if info.kept and len(attachments) >= max_attachments:
                info.kept = False
                info.reason = f"more than {max_attachments} attachments"
            parsed.attachments.append(info)
            if info.kept:
                attachments.append(
                    {
                        "filename": info.filename,
                        "content_type": info.content_type,
                        "data_b64": base64.b64encode(payload).decode(),
                        "sha256": info.sha256,
                        "size": info.size,
                    }
                )
                safe = safe_filename(info.filename)
                stem, dot, ext = safe.rpartition(".")
                n = 1
                while safe in seen_names:
                    n += 1
                    safe = f"{stem or ext}-{n}{dot}{ext}" if dot else f"{safe}-{n}"
                seen_names.add(safe)
                parsed.kept_payloads[safe] = payload
            else:
                parsed.warnings.append(f"dropped attachment {info.filename!r}: {info.reason}")
        elif ctype == "text/plain" and not body_text:
            try:
                body_text = part.get_content()
            except (LookupError, UnicodeDecodeError):
                body_text = (part.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
        elif ctype == "text/html" and not body_html:
            try:
                body_html = part.get_content()
            except (LookupError, UnicodeDecodeError):
                body_html = (part.get_payload(decode=True) or b"").decode("utf-8", errors="replace")

    stamp = (received_at or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
    parsed.intake = {
        "headers": headers,
        "body_text": body_text,
        "body_html": body_html,
        "attachments": attachments,
        "source": "email",
        "received_at": stamp,
    }
    return parsed
