"""Global request budget for the shared Akamai team key.

The service allows 60 requests/min per team across chat, embeddings and images. One process
targets ~45/min (``VOUCH_LLM_RPM``) with a sliding 60-second window so bursts from the API,
the smoke test and the demo never trip the shared quota. A 429 with ``x-ratelimit-reset``
(seconds) pauses the window.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, rpm: int = 45, window_s: float = 60.0) -> None:
        self.rpm = max(1, rpm)
        self.window_s = window_s
        self._times: deque[float] = deque()
        self._lock = threading.Lock()
        self._paused_until = 0.0
        self.waits = 0
        self.total_wait_s = 0.0

    def _next_slot_delay(self) -> float:
        now = time.monotonic()
        with self._lock:
            while self._times and now - self._times[0] >= self.window_s:
                self._times.popleft()
            delay = 0.0
            if now < self._paused_until:
                delay = self._paused_until - now
            elif len(self._times) >= self.rpm:
                delay = self.window_s - (now - self._times[0])
            if delay <= 0:
                self._times.append(now)
        return max(0.0, delay)

    def acquire(self, timeout: float | None = 120.0) -> None:
        start = time.monotonic()
        while True:
            delay = self._next_slot_delay()
            if delay <= 0:
                return
            if timeout is not None and time.monotonic() - start + delay > timeout:
                raise TimeoutError("rate limiter: no request slot within timeout")
            self.waits += 1
            self.total_wait_s += delay
            time.sleep(min(delay, 1.0))

    async def acquire_async(self, timeout: float | None = 120.0) -> None:
        start = time.monotonic()
        while True:
            delay = self._next_slot_delay()
            if delay <= 0:
                return
            if timeout is not None and time.monotonic() - start + delay > timeout:
                raise TimeoutError("rate limiter: no request slot within timeout")
            self.waits += 1
            self.total_wait_s += delay
            await asyncio.sleep(min(delay, 1.0))

    def penalize(self, seconds: float) -> None:
        with self._lock:
            self._paused_until = max(self._paused_until, time.monotonic() + max(0.0, seconds))

    def in_window(self) -> int:
        now = time.monotonic()
        with self._lock:
            while self._times and now - self._times[0] >= self.window_s:
                self._times.popleft()
            return len(self._times)

    def snapshot(self) -> dict:
        return {
            "rpm_target": self.rpm,
            "in_window": self.in_window(),
            "waits": self.waits,
            "total_wait_s": round(self.total_wait_s, 2),
        }
