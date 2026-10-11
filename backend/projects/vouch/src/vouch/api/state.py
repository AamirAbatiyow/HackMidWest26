"""Process-wide service handle shared by the routers (and swapped by tests)."""

from __future__ import annotations

import threading
from typing import Any

from vouch.engine import VouchEngine
from vouch.service import VouchService

_state: dict[str, Any] = {"service": None, "redteam": None}
_lock = threading.Lock()


def get_service() -> VouchService:
    with _lock:
        if _state["service"] is None:
            from vouch.config import get_settings

            _state["service"] = VouchService(get_settings())
        return _state["service"]


def set_service(service: VouchService | VouchEngine | None) -> None:
    """Install a service (or a bare engine, e.g. from the test fixtures) for the API to use."""
    if isinstance(service, VouchEngine):
        from vouch.audit import AuditStore

        service = VouchService(
            service.settings, engine=service, store=AuditStore("sqlite://"), seed_demo=False, restore=False
        )
    with _lock:
        _state["service"] = service
        _state["redteam"] = None


def get_engine() -> VouchEngine:
    return get_service().engine
