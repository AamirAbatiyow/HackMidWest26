"""Optional Valkey/Redis client. Returns None when REDIS_URL is unset so callers can degrade gracefully."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from hm_storage.settings import get_storage_settings


@lru_cache
def get_redis() -> Any | None:
    url = get_storage_settings().redis_url
    if not url:
        return None
    import redis

    return redis.Redis.from_url(url, decode_responses=True)
