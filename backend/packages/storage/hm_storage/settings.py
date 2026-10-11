from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr

from hm_core.config import HMSettings


class StorageSettings(HMSettings):
    database_url: str = "postgresql+psycopg://hack:hack@localhost:5432/hack"
    redis_url: str = ""

    # Akamai Object Storage endpoint looks like https://us-ord-1.linodeobjects.com ; SeaweedFS (docker compose) locally.
    object_storage_endpoint: str = "http://localhost:9000"
    object_storage_region: str = "us-ord-1"
    object_storage_bucket: str = "hack-artifacts"
    object_storage_access_key: SecretStr = SecretStr("")
    object_storage_secret_key: SecretStr = SecretStr("")


@lru_cache
def get_storage_settings() -> StorageSettings:
    return StorageSettings()
