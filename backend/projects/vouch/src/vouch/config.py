"""Settings for the Vouch backend, read from the environment (and a local .env).

Every Akamai service is optional. When its setting is missing the backend uses a local
fallback and says so on /health. Secrets are never read from files other than .env and
never logged.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
POLICY_DIR = PROJECT_ROOT / "policies"
SAMPLES_DIR = PROJECT_ROOT / "samples"

LlmMode = Literal["live", "template"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    # --- product / server ---
    app_name: str = Field(default="Vouch", alias="VOUCH_APP_NAME")
    version: str = Field(default="0.1.0", alias="VOUCH_VERSION")
    host: str = Field(default="0.0.0.0", alias="VOUCH_HOST")
    port: int = Field(default=8101, alias="VOUCH_PORT")
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173",
        alias="VOUCH_CORS_ORIGINS",
    )
    region: str = Field(default="us-ord (Chicago)", alias="VOUCH_REGION")
    approval_limit_cents: int = Field(default=500_000, alias="VOUCH_APPROVAL_LIMIT_CENTS")
    new_vendor_limit_cents: int = Field(default=250_000, alias="VOUCH_NEW_VENDOR_LIMIT_CENTS")
    data_dir: Path = Field(default=BACKEND_ROOT / "data", alias="VOUCH_DATA_DIR")
    seed_demo: bool = Field(default=True, alias="VOUCH_SEED_DEMO")
    seed_live: bool = Field(default=False, alias="VOUCH_SEED_LIVE")

    # --- LLM: Akamai hosted inference (OpenAI-compatible) ---
    llm_mode_setting: Literal["auto", "live", "template"] = Field(default="auto", alias="VOUCH_LLM_MODE")
    akamai_api_key: str = Field(default="", alias="AKAMAI_INFERENCE_API_KEY")
    akamai_base_url: str = Field(
        default="https://ws.akamai-workshops.com/v1", alias="AKAMAI_INFERENCE_BASE_URL"
    )
    akamai_chat_model: str = Field(default="hackathon-chat", alias="AKAMAI_INFERENCE_MODEL")
    akamai_embedding_model: str = Field(default="hackathon-embedding", alias="AKAMAI_EMBEDDING_MODEL")
    llm_rpm: int = Field(default=45, alias="VOUCH_LLM_RPM")
    llm_max_tokens: int = Field(default=1024, alias="VOUCH_LLM_MAX_TOKENS")
    llm_timeout_s: float = Field(default=30.0, alias="VOUCH_LLM_TIMEOUT_S")
    llm_max_retries: int = Field(default=1, alias="VOUCH_LLM_MAX_RETRIES")

    # --- private model server inside the VPC (optional) ---
    model_server_url: str = Field(default="", alias="VOUCH_MODEL_SERVER_URL")

    # --- data stores ---
    database_url: str = Field(default="", alias="DATABASE_URL")
    obj_endpoint: str = Field(default="", alias="OBJ_ENDPOINT")
    obj_bucket: str = Field(default="", alias="OBJ_BUCKET")
    obj_access_key: str = Field(default="", alias="OBJ_ACCESS_KEY")
    obj_secret_key: str = Field(default="", alias="OBJ_SECRET_KEY")

    # --- deployment metadata shown on /health ---
    behind_nodebalancer: bool = Field(default=False, alias="VOUCH_BEHIND_NODEBALANCER")
    firewall_label: str = Field(default="", alias="VOUCH_FIREWALL_LABEL")
    vpc_label: str = Field(default="", alias="VOUCH_VPC_LABEL")

    @property
    def llm_mode(self) -> LlmMode:
        if self.llm_mode_setting == "auto":
            return "live" if self.akamai_api_key else "template"
        return self.llm_mode_setting

    @property
    def has_llm_key(self) -> bool:
        return bool(self.akamai_api_key)

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
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{(self.data_dir / 'vouch.sqlite3').as_posix()}"

    @property
    def is_postgres(self) -> bool:
        return self.effective_database_url.startswith("postgresql")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def _load_env_files() -> None:
    # .env in the backend root wins over the shell, like the Akamai workshop notebooks; a
    # repo-root .env is also honoured so one file can serve frontend and backend.
    for candidate in (BACKEND_ROOT / ".env", BACKEND_ROOT.parent / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    if not os.environ.get("VOUCH_SKIP_DOTENV"):
        _load_env_files()
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
