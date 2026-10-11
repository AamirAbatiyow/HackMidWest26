"""Receiver settings, from environment variables only (12-factor; no config files in the image)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ALLOWED_EXTENSIONS = ("pdf", "png", "jpg", "jpeg", "xlsx", "csv", "txt")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int(name: str, default: int) -> int:
    raw = _env(name)
    return int(raw) if raw else default


def _float(name: str, default: float) -> float:
    raw = _env(name)
    return float(raw) if raw else default


def _bool(name: str, default: bool = False) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = _env(name)
    if not raw:
        return default
    return tuple(x.strip().lower().lstrip(".") for x in raw.split(",") if x.strip())


@dataclass
class Settings:
    # --- identity / recipients ---
    mail_domain: str = "vouch.local"
    accept_local_parts: tuple[str, ...] = ("business",)
    accept_any_recipient: bool = False  # testing only
    smtp_hostname: str = ""  # banner / HELO identity; defaults to mail.<mail_domain>

    # --- listeners ---
    # Container listeners: all interfaces on purpose; the VPC firewall / docker port mapping scopes them.
    smtp_host: str = "0.0.0.0"  # noqa: S104
    smtp_ports: tuple[int, ...] = (25, 2525)
    http_host: str = "0.0.0.0"  # noqa: S104
    http_port: int = 8025

    # --- limits ---
    max_message_bytes: int = 15 * 1024 * 1024
    max_attachment_bytes: int = 10 * 1024 * 1024
    max_attachments: int = 10
    allowed_extensions: tuple[str, ...] = DEFAULT_ALLOWED_EXTENSIONS

    # --- storage ---
    data_dir: Path = field(default_factory=lambda: Path("/data"))
    recent_limit: int = 20
    obj_endpoint: str = ""
    obj_bucket: str = ""
    obj_access_key: str = ""
    obj_secret_key: str = ""
    obj_prefix: str = "mail/"

    # --- forwarding to the backend ---
    # json → POST IntakeRequest JSON to e.g. http://10.0.0.5:8000/v1/intake
    # eml  → multipart upload (field "file") to e.g. http://10.0.0.5:8000/v1/intake/eml
    backend_intake_url: str = ""
    backend_intake_format: str = "json"
    backend_submitted_by: str = "ap-inbox"  # the backend's "who submitted this" label
    intake_shared_secret: str = ""
    intake_secret_header: str = "X-Vouch-Intake-Secret"  # noqa: S105 - header *name*, not a secret
    delivery_max_attempts: int = 10  # ≈4 min of backoff before dead-lettering (backend restarts survive)
    delivery_backoff_base_s: float = 1.0
    delivery_backoff_max_s: float = 60.0
    delivery_timeout_s: float = 20.0
    shutdown_drain_s: float = 10.0  # how long SIGTERM waits for queued forwards before exiting
    requeue_scan_limit: int = 500  # newest message dirs inspected for unfinished deliveries at start

    log_level: str = "INFO"

    @property
    def hostname(self) -> str:
        return self.smtp_hostname or f"mail.{self.mail_domain}"

    @property
    def accepted_addresses(self) -> set[str]:
        return {f"{lp}@{self.mail_domain}".lower() for lp in self.accept_local_parts}

    @property
    def has_bucket(self) -> bool:
        return all([self.obj_endpoint, self.obj_bucket, self.obj_access_key, self.obj_secret_key])

    @property
    def forwarding_enabled(self) -> bool:
        return bool(self.backend_intake_url)

    def accepts(self, address: str) -> bool:
        address = (address or "").strip().strip("<>").lower()
        if self.accept_any_recipient:
            return "@" in address
        return address in self.accepted_addresses

    def public_view(self) -> dict:
        """Settings safe to show on /health (no secrets)."""
        return {
            "mail_domain": self.mail_domain,
            "accepting": sorted(self.accepted_addresses) if not self.accept_any_recipient else ["*"],
            "smtp_ports": list(self.smtp_ports),
            "http_port": self.http_port,
            "max_message_bytes": self.max_message_bytes,
            "max_attachment_bytes": self.max_attachment_bytes,
            "allowed_extensions": list(self.allowed_extensions),
            "backend_intake_url": self.backend_intake_url or None,
            "backend_intake_format": self.backend_intake_format,
            "shared_secret_configured": bool(self.intake_shared_secret),
            "object_storage": {"enabled": self.has_bucket, "bucket": self.obj_bucket or None},
            "data_dir": str(self.data_dir),
        }


def load_settings() -> Settings:
    s = Settings()
    s.mail_domain = _env("MAIL_DOMAIN", s.mail_domain).lower()
    s.accept_local_parts = _list("MAIL_ACCEPT", s.accept_local_parts)
    s.accept_any_recipient = _bool("MAIL_ACCEPT_ANY", s.accept_any_recipient)
    s.smtp_hostname = _env("SMTP_HOSTNAME", s.smtp_hostname)
    s.smtp_host = _env("SMTP_HOST", s.smtp_host)
    ports = _env("SMTP_PORTS")
    if ports:
        s.smtp_ports = tuple(int(p) for p in ports.split(",") if p.strip())
    s.http_host = _env("HTTP_HOST", s.http_host)
    s.http_port = _int("HTTP_PORT", s.http_port)
    s.max_message_bytes = _int("MAX_MESSAGE_BYTES", s.max_message_bytes)
    s.max_attachment_bytes = _int("MAX_ATTACHMENT_BYTES", s.max_attachment_bytes)
    s.max_attachments = _int("MAX_ATTACHMENTS", s.max_attachments)
    s.allowed_extensions = _list("ALLOWED_EXTENSIONS", s.allowed_extensions)
    s.data_dir = Path(_env("DATA_DIR", str(s.data_dir)))
    s.recent_limit = _int("RECENT_LIMIT", s.recent_limit)
    s.obj_endpoint = _env("OBJ_ENDPOINT")
    s.obj_bucket = _env("OBJ_BUCKET")
    s.obj_access_key = _env("OBJ_ACCESS_KEY")
    s.obj_secret_key = _env("OBJ_SECRET_KEY")
    s.obj_prefix = _env("OBJ_PREFIX", s.obj_prefix)
    s.backend_intake_url = _env("BACKEND_INTAKE_URL")
    s.backend_intake_format = _env("BACKEND_INTAKE_FORMAT", s.backend_intake_format).lower() or "json"
    s.backend_submitted_by = _env("BACKEND_SUBMITTED_BY", s.backend_submitted_by)
    s.intake_shared_secret = _env("INTAKE_SHARED_SECRET")
    s.intake_secret_header = _env("INTAKE_SECRET_HEADER", s.intake_secret_header)
    s.delivery_max_attempts = _int("DELIVERY_MAX_ATTEMPTS", s.delivery_max_attempts)
    s.delivery_backoff_base_s = _float("DELIVERY_BACKOFF_BASE_S", s.delivery_backoff_base_s)
    s.delivery_backoff_max_s = _float("DELIVERY_BACKOFF_MAX_S", s.delivery_backoff_max_s)
    s.delivery_timeout_s = _float("DELIVERY_TIMEOUT_S", s.delivery_timeout_s)
    s.shutdown_drain_s = _float("SHUTDOWN_DRAIN_S", s.shutdown_drain_s)
    s.requeue_scan_limit = _int("REQUEUE_SCAN_LIMIT", s.requeue_scan_limit)
    s.log_level = _env("LOG_LEVEL", s.log_level).upper()
    return s
