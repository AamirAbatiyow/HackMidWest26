"""Settings for the invoice creator, read from the environment (and an optional local .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines, # comments). Existing variables win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class Settings:
    # --- SMTP delivery to the mail receiver ---
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 2525
    mail_to: str = "business@vouch.local"
    smtp_timeout_s: float = 15.0

    # --- HTTP fallbacks ---
    # eml  → multipart upload (field "file") to e.g. http://127.0.0.1:8101/v1/intake/eml
    # json → IntakeRequest JSON to e.g. http://127.0.0.1:8101/v1/intake
    backend_intake_url: str = ""
    backend_intake_format: str = "eml"
    receiver_inbound_url: str = ""  # e.g. http://127.0.0.1:8025/inbound
    receiver_api_url: str = ""  # receiver HTTP API base for /health and /recent; derived when empty
    intake_shared_secret: str = ""
    intake_secret_header: str = "X-Vouch-Intake-Secret"  # noqa: S105 - header *name*, not a secret
    http_timeout_s: float = 20.0

    # --- simulation ---
    authserv_id: str = "mx.vouch.local"  # authserv-id written into Authentication-Results
    owner_name: str = "Grand Avenue Trading LLC"
    owner_address: str = "500 Grand Blvd, Suite 210, Kansas City, MO 64106"

    # --- web UI / local state ---
    host: str = "127.0.0.1"
    port: int = 8300
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")

    @property
    def receiver_api_base(self) -> str:
        """Where the receiver's read-only API lives: explicit RECEIVER_API_URL, else the host of
        RECEIVER_INBOUND_URL, else port 8025 on the SMTP host (the receiver's default)."""
        if self.receiver_api_url:
            return self.receiver_api_url.rstrip("/")
        if self.receiver_inbound_url:
            return self.receiver_inbound_url.rsplit("/inbound", 1)[0].rstrip("/")
        return f"http://{self.smtp_host}:8025"

    @property
    def deliveries(self) -> list[dict[str, str]]:
        """Delivery targets the UI can offer, derived from configuration."""
        out = [
            {
                "id": "smtp",
                "label": f"SMTP → {self.smtp_host}:{self.smtp_port}",
                "detail": f"Direct SMTP to the mail receiver, RCPT TO {self.mail_to}",
            }
        ]
        if self.receiver_inbound_url:
            out.append(
                {
                    "id": "receiver_http",
                    "label": "HTTP → receiver /inbound",
                    "detail": f"POST the .eml to {self.receiver_inbound_url} (when SMTP is blocked)",
                }
            )
        if self.backend_intake_url:
            out.append(
                {
                    "id": "backend",
                    "label": "HTTP → backend intake",
                    "detail": f"POST {self.backend_intake_format} straight to {self.backend_intake_url}",
                }
            )
        out.append({"id": "none", "label": "Build only (download .eml)", "detail": "No delivery"})
        return out


def load_settings() -> Settings:
    if not os.environ.get("DEMO_SKIP_DOTENV"):
        _load_dotenv(PROJECT_ROOT / ".env")
    s = Settings()
    s.smtp_host = _env("DEMO_SMTP_HOST", s.smtp_host)
    s.smtp_port = int(_env("DEMO_SMTP_PORT", str(s.smtp_port)))
    s.mail_to = _env("DEMO_MAIL_TO", s.mail_to)
    s.smtp_timeout_s = float(_env("DEMO_SMTP_TIMEOUT_S", str(s.smtp_timeout_s)))
    s.backend_intake_url = _env("BACKEND_INTAKE_URL", s.backend_intake_url)
    s.backend_intake_format = _env("BACKEND_INTAKE_FORMAT", s.backend_intake_format).lower() or "eml"
    s.receiver_inbound_url = _env("RECEIVER_INBOUND_URL", s.receiver_inbound_url)
    s.receiver_api_url = _env("RECEIVER_API_URL", s.receiver_api_url)
    s.intake_shared_secret = _env("INTAKE_SHARED_SECRET", s.intake_shared_secret)
    s.intake_secret_header = _env("INTAKE_SECRET_HEADER", s.intake_secret_header)
    s.http_timeout_s = float(_env("DEMO_HTTP_TIMEOUT_S", str(s.http_timeout_s)))
    s.authserv_id = _env("DEMO_AUTHSERV_ID", s.authserv_id)
    s.owner_name = _env("DEMO_OWNER_NAME", s.owner_name)
    s.owner_address = _env("DEMO_OWNER_ADDRESS", s.owner_address)
    s.host = _env("DEMO_HOST", s.host)
    s.port = int(_env("DEMO_PORT", str(s.port)))
    s.data_dir = Path(_env("DEMO_DATA_DIR", str(s.data_dir)))
    return s
