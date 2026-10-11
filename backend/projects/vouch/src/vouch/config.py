"""Settings for the Vouch backend, read from the environment and a local .env.

Every Akamai service is optional: when its setting is missing the backend uses a local fallback
and says so on /health. Env vars are prefixed `VOUCH_` (e.g. VOUCH_PORT=9000) except the shared
ones used by the hm_* packages (AKAMAI_INFERENCE_*, DATABASE_URL, OBJECT_STORAGE_*,
SETTLEMENT_ADAPTER). Secrets are never read from files other than .env and never logged.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import AliasChoices, Field
from pydantic_settings import SettingsConfigDict

from hm_core.config import HMSettings

BACKEND_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
POLICY_DIR = PROJECT_ROOT / "policies"
SAMPLES_DIR = PROJECT_ROOT / "samples"

LlmMode = Literal["live", "offline"]
_ENV_FILES = (BACKEND_ROOT.parent / ".env", BACKEND_ROOT / ".env")  # later wins


class Settings(HMSettings):
    """Project settings. `VOUCH_*` for everything Vouch-specific; shared names are aliased explicitly."""

    model_config = SettingsConfigDict(
        env_prefix="VOUCH_",
        env_file=_ENV_FILES,
        extra="ignore",
        case_sensitive=False,
        env_ignore_empty=True,
        populate_by_name=True,
    )

    # --- product / server ---
    app_name: str = "Vouch"
    version: str = "0.1.0"
    host: str = "0.0.0.0"  # noqa: S104 - container/VM bind address; the NodeBalancer fronts it
    port: int = 8101
    inference_port: int = 8201
    # Containers/k8s set the generic INFERENCE_URL; local dev uses the default.
    inference_url: str = Field(
        "http://localhost:8201", validation_alias=AliasChoices("VOUCH_INFERENCE_URL", "INFERENCE_URL")
    )
    cors_origins: str = Field(
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://localhost:3000",
        validation_alias=AliasChoices("VOUCH_CORS_ORIGINS", "CORS_ALLOW_ORIGINS"),
    )
    region: str = "us-ord (Chicago)"
    data_dir: Path = BACKEND_ROOT / "data"
    seed_demo: bool = True  # seed the vendor master + scripted run when the store is empty

    # --- risk model ---
    model_name: str = "vouch-risk"
    model_registry_dir: Path = Field(
        BACKEND_ROOT / "artifacts" / "models", validation_alias="MODEL_REGISTRY_DIR"
    )
    # auto: inference service if reachable, else in-process torch model, else heuristic fallback.
    scorer: Literal["auto", "http", "local", "heuristic"] = "auto"
    lime_samples: int = 400
    model_server_url: str = ""  # private model-serving Linode inside the VPC (shown on /health)

    # --- LLM: Akamai hosted inference (OpenAI-compatible) through Strands ---
    # auto: live when AKAMAI_INFERENCE_API_KEY (or Bedrock) is configured, else deterministic templates.
    llm_mode: Literal["auto", "live", "offline", "template"] = "auto"
    akamai_api_key: str = Field("", validation_alias="AKAMAI_INFERENCE_API_KEY")
    akamai_base_url: str = Field(
        "https://ws.akamai-workshops.com/v1", validation_alias="AKAMAI_INFERENCE_BASE_URL"
    )
    akamai_chat_model: str = Field("hackathon-chat", validation_alias="AKAMAI_INFERENCE_MODEL")
    akamai_embedding_model: str = Field("hackathon-embedding", validation_alias="AKAMAI_EMBEDDING_MODEL")
    llm_rpm: int = 45  # team key allows 60/min shared by chat, embeddings and images
    llm_max_tokens: int = 1024  # service default is 512, maximum 4096
    llm_timeout_s: float = 45.0
    llm_max_retries: int = 1

    # --- money limits, integer cents ---
    approval_limit_cents: int = 500_000  # $5,000 clerk approval limit
    fast_pay_limit_cents: int = 250_000  # $2,500
    single_payment_limit_cents: int = 5_000_000  # $50,000
    batch_limit_cents: int = 10_000_000  # $100,000 per batch

    # --- cash-forecast stub ---
    opening_balance_cents: int = 18_500_000
    cash_buffer_cents: int = 2_500_000

    owner_name: str = "Dana Whitfield"
    business_name: str = "Heartland Provisions Co."

    # --- data stores ---
    database_url: str = Field("", validation_alias="DATABASE_URL")
    settlement_adapter: str = Field("mock", validation_alias="SETTLEMENT_ADAPTER")
    obj_endpoint: str = Field("", validation_alias=AliasChoices("OBJECT_STORAGE_ENDPOINT", "OBJ_ENDPOINT"))
    obj_region: str = Field("us-ord-1", validation_alias=AliasChoices("OBJECT_STORAGE_REGION", "OBJ_REGION"))
    obj_bucket: str = Field("", validation_alias=AliasChoices("OBJECT_STORAGE_BUCKET", "OBJ_BUCKET"))
    obj_access_key: str = Field(
        "", validation_alias=AliasChoices("OBJECT_STORAGE_ACCESS_KEY", "OBJ_ACCESS_KEY")
    )
    obj_secret_key: str = Field(
        "", validation_alias=AliasChoices("OBJECT_STORAGE_SECRET_KEY", "OBJ_SECRET_KEY")
    )

    # --- deployment metadata shown on /health ---
    behind_nodebalancer: bool = False
    firewall_label: str = ""
    vpc_label: str = ""

    @property
    def has_llm_key(self) -> bool:
        return bool(self.akamai_api_key)

    @property
    def effective_llm_mode(self) -> LlmMode:
        if self.llm_mode == "auto":
            return "live" if self.has_llm_key else "offline"
        return "offline" if self.llm_mode == "template" else self.llm_mode

    @property
    def has_bucket(self) -> bool:
        return all([self.obj_endpoint, self.obj_bucket, self.obj_access_key, self.obj_secret_key])

    @property
    def effective_database_url(self) -> str:
        if self.database_url:
            url = self.database_url
            # SQLAlchemy needs the psycopg (v3) driver name; accept plain postgres URLs from Akamai.
            if url.startswith("postgres://"):
                url = "postgresql+psycopg://" + url[len("postgres://") :]
            elif url.startswith("postgresql://"):
                url = "postgresql+psycopg://" + url[len("postgresql://") :]
            return url
        return self.sqlite_url

    @property
    def sqlite_url(self) -> str:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{(self.data_dir / 'vouch.sqlite3').as_posix()}"

    @property
    def is_postgres(self) -> bool:
        return self.effective_database_url.startswith("postgresql")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def _load_env_files() -> None:
    # Export .env values so the hm_* settings classes (which read the process environment) see the
    # same configuration regardless of the working directory. Real environment variables always win.
    for candidate in reversed(_ENV_FILES):
        if candidate.exists():
            load_dotenv(candidate, override=False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    if not os.environ.get("VOUCH_SKIP_DOTENV"):
        _load_env_files()
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
