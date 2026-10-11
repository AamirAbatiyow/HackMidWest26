"""API-key auth stub. Disabled when API_KEYS is empty (local dev); otherwise checks `X-API-Key`.

TODO(hackathon): swap for real auth only if a judge-facing flow needs it.
"""

from __future__ import annotations

import hmac

from fastapi import Security
from fastapi.security import APIKeyHeader

from hm_core.config import get_app_settings
from hm_core.errors import UnauthorizedError

_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: str | None = Security(_header)) -> str | None:
    settings = get_app_settings()
    if not settings.auth_enabled:
        return None
    if api_key and any(hmac.compare_digest(api_key, k) for k in settings.api_keys):
        return api_key
    raise UnauthorizedError("missing or invalid X-API-Key")
