"""Settings base classes.

Every package/project defines its own small `BaseSettings` subclass that inherits `env_file`
handling from `HMSettings`, so one root `.env` configures the whole monorepo. Real environment
variables always win over `.env`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def find_env_file(start: Path | None = None) -> Path | None:
    """Walk up from `start` (default: cwd) and return the first `.env` found."""
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        candidate = folder / ".env"
        if candidate.is_file():
            return candidate
    return None


def split_csv(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [v.strip() for v in value if v.strip()]
    return [v.strip() for v in value.split(",") if v.strip()]


class HMSettings(BaseSettings):
    """Base for all settings classes: reads the nearest `.env`, ignores unknown keys and blank values."""

    model_config = SettingsConfigDict(
        env_file=find_env_file(), extra="ignore", case_sensitive=False, env_ignore_empty=True
    )


CsvList = Annotated[list[str], NoDecode]


class AppSettings(HMSettings):
    app_env: Literal["local", "dev", "staging", "prod", "test"] = "local"
    log_level: str = "INFO"
    log_json: bool = False
    cors_allow_origins: CsvList = Field(default_factory=lambda: ["*"])
    api_keys: CsvList = Field(default_factory=list)

    @field_validator("cors_allow_origins", "api_keys", mode="before")
    @classmethod
    def _split(cls, value: str | list[str] | None) -> list[str]:
        return split_csv(value)

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_keys)


@lru_cache
def get_app_settings() -> AppSettings:
    return AppSettings()
