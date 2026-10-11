"""Sliding-window rate limiter usable from both threads and asyncio.

Guarantees at most `max_calls` acquisitions in any rolling `period` seconds *within one process*.
Run a single API process per team key (or move this to Valkey) if you scale out.
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from collections import deque
from collections.abc import Callable

from hm_core.errors import RateLimitedError


class RateLimiter:
    def __init__(self, max_calls: int, period: float = 60.0, clock: Callable[[], float] = time.monotonic):
        if max_calls < 1:
            raise ValueError("max_calls must be >= 1")
        self.max_calls = max_calls
        self.period = period
        self._clock = clock
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def _evict(self, now: float) -> None:
        while self._calls and now - self._calls[0] >= self.period:
            self._calls.popleft()

    def _reserve(self) -> float:
        """Take a slot if one is free (returns 0.0), else return seconds until one frees up."""
        with self._lock:
            now = self._clock()
            self._evict(now)
            if len(self._calls) < self.max_calls:
                self._calls.append(now)
                return 0.0
            return max(self._calls[0] + self.period - now, 0.001)

    def try_acquire(self) -> bool:
        return self._reserve() == 0.0

    def acquire(self, timeout: float | None = None) -> None:
        start = self._clock()
        while (wait := self._reserve()) > 0:
            if timeout is not None and self._clock() - start + wait > timeout:
                raise RateLimitedError(f"rate limiter wait would exceed {timeout}s")
            time.sleep(wait)

    async def acquire_async(self, timeout: float | None = None) -> None:
        start = self._clock()
        while (wait := self._reserve()) > 0:
            if timeout is not None and self._clock() - start + wait > timeout:
                raise RateLimitedError(f"rate limiter wait would exceed {timeout}s")
            await asyncio.sleep(wait)

    @property
    def remaining(self) -> int:
        with self._lock:
            self._evict(self._clock())
            return self.max_calls - len(self._calls)


_registry: dict[str, RateLimiter] = {}
_registry_lock = threading.Lock()


def limiter_key(base_url: str, api_key: str) -> str:
    return f"{base_url}|{hashlib.sha256(api_key.encode()).hexdigest()[:12]}"


def get_shared_limiter(key: str, max_calls: int, period: float = 60.0) -> RateLimiter:
    """One limiter per (endpoint, key) per process, shared by raw OpenAI clients and Strands agents."""
    with _registry_lock:
        if key not in _registry:
            _registry[key] = RateLimiter(max_calls, period)
        return _registry[key]
