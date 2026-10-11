from __future__ import annotations

import os
from functools import lru_cache

from pydantic import SecretStr, field_validator

from hm_core.config import HMSettings


def _env_with_fallback(primary: str, *fallbacks: str) -> str:
    """Read an env var with fallback names (for alternate naming conventions)."""
    val = os.environ.get(primary, "")
    if not val:
        for fb in fallbacks:
            val = os.environ.get(fb, "")
            if val:
                break
    return val


class StorageSettings(HMSettings):
    database_url: str = "postgresql+psycopg://hack:hack@localhost:5432/hack"
    redis_url: str = ""

    # Akamai Object Storage endpoint looks like https://us-ord-1.linodeobjects.com ; SeaweedFS (docker compose) locally.
    # Accepts multiple env var naming conventions:
    #   OBJECT_STORAGE_* (pydantic default)
    #   OBJ_* (preferred short form)
    #   LINODE_OBJ_* (fallback for stored credentials)
    object_storage_endpoint: str = "http://localhost:9000"
    object_storage_region: str = "us-ord-1"
    object_storage_bucket: str = "hack-artifacts"
    object_storage_access_key: SecretStr = SecretStr("")
    object_storage_secret_key: SecretStr = SecretStr("")

    @field_validator("object_storage_endpoint", mode="before")
    @classmethod
    def _endpoint_fallback(cls, v: str) -> str:
        return v or _env_with_fallback("OBJ_ENDPOINT")

    @field_validator("object_storage_region", mode="before")
    @classmethod
    def _region_fallback(cls, v: str) -> str:
        return v or _env_with_fallback("OBJ_REGION")

    @field_validator("object_storage_bucket", mode="before")
    @classmethod
    def _bucket_fallback(cls, v: str) -> str:
        return v or _env_with_fallback("OBJ_BUCKET")

    @field_validator("object_storage_access_key", mode="before")
    @classmethod
    def _access_key_fallback(cls, v: str | SecretStr) -> str:
        val = v.get_secret_value() if isinstance(v, SecretStr) else v
        return val or _env_with_fallback("OBJ_ACCESS_KEY", "LINODE_OBJ_ACCESS_KEY")

    @field_validator("object_storage_secret_key", mode="before")
    @classmethod
    def _secret_key_fallback(cls, v: str | SecretStr) -> str:
        val = v.get_secret_value() if isinstance(v, SecretStr) else v
        return val or _env_with_fallback("OBJ_SECRET_KEY", "LINODE_OBJ_SECRET_KEY")


@lru_cache
def get_storage_settings() -> StorageSettings:
    return StorageSettings()
