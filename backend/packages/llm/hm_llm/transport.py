"""httpx transports that rate-limit every outbound request and retry 429/5xx with backoff.

Plug into any httpx-based SDK (OpenAI, etc.) via `httpx.Client(transport=...)`.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import httpx

from hm_llm.ratelimit import RateLimiter
from hm_llm.retry import backoff_delay, parse_retry_after

TRANSPORT_RETRY_STATUS = frozenset({429, 502, 503, 504})


class _RetryPolicy:
    def __init__(self, max_retries: int, base_delay: float, max_delay: float) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    def should_retry(self, response: httpx.Response, attempt: int) -> bool:
        return response.status_code in TRANSPORT_RETRY_STATUS and attempt < self.max_retries

    def delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = parse_retry_after(response.headers.get("retry-after"))
        delay = retry_after if retry_after is not None else backoff_delay(attempt, self.base_delay)
        return min(delay, self.max_delay)


class RateLimitedTransport(httpx.BaseTransport):
    def __init__(
        self,
        limiter: RateLimiter,
        inner: httpx.BaseTransport | None = None,
        max_retries: int = 4,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        sleep: Callable[[float], Any] = time.sleep,
    ) -> None:
        self.limiter = limiter
        self.inner = inner or httpx.HTTPTransport()
        self.policy = _RetryPolicy(max_retries, base_delay, max_delay)
        self._sleep = sleep

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        attempt = 0
        while True:
            self.limiter.acquire()
            response = self.inner.handle_request(request)
            if not self.policy.should_retry(response, attempt):
                return response
            delay = self.policy.delay(response, attempt)
            response.close()
            self._sleep(delay)
            attempt += 1

    def close(self) -> None:
        self.inner.close()


class AsyncRateLimitedTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        limiter: RateLimiter,
        inner: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 4,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> None:
        self.limiter = limiter
        self.inner = inner or httpx.AsyncHTTPTransport()
        self.policy = _RetryPolicy(max_retries, base_delay, max_delay)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        attempt = 0
        while True:
            await self.limiter.acquire_async()
            response = await self.inner.handle_async_request(request)
            if not self.policy.should_retry(response, attempt):
                return response
            delay = self.policy.delay(response, attempt)
            await response.aclose()
            await asyncio.sleep(delay)
            attempt += 1

    async def aclose(self) -> None:
        await self.inner.aclose()
