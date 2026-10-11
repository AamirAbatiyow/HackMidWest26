"""Exponential backoff with full jitter that honors `Retry-After`. Works on sync and async callables."""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import random
import time
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

log = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
F = TypeVar("F", bound=Callable[..., Any])


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 30.0, jitter: bool = True) -> float:
    ceiling = min(cap, base * (2**attempt))
    return random.uniform(0, ceiling) if jitter else ceiling


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        return max(parsedate_to_datetime(value).timestamp() - time.time(), 0.0)
    except (TypeError, ValueError):
        return None


def _status_and_retry_after(exc: BaseException) -> tuple[int | None, float | None]:
    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is None and response is not None:
        headers = getattr(response, "headers", None) or {}
        retry_after = parse_retry_after(headers.get("retry-after"))
    return status, retry_after


def is_retryable(exc: BaseException, extra: tuple[type[BaseException], ...] = ()) -> bool:
    if extra and isinstance(exc, extra):
        return True
    status, _ = _status_and_retry_after(exc)
    if status is not None:
        return status in RETRYABLE_STATUS
    name = type(exc).__name__
    return name in {"APIConnectionError", "APITimeoutError", "ConnectError", "ReadTimeout", "ConnectTimeout"}


def retry_with_backoff(
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retry_on: tuple[type[BaseException], ...] = (),
    sleep: Callable[[float], Any] | None = None,
) -> Callable[[F], F]:
    """Retry 429/5xx/connection errors (and any `retry_on` types) with backoff."""

    def delay_for(attempt: int, exc: BaseException) -> float:
        _, retry_after = _status_and_retry_after(exc)
        return min(retry_after if retry_after is not None else backoff_delay(attempt, base_delay), max_delay)

    def decorator(fn: F) -> F:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                for attempt in range(max_attempts):
                    try:
                        return await fn(*args, **kwargs)
                    except Exception as exc:
                        if attempt == max_attempts - 1 or not is_retryable(exc, retry_on):
                            raise
                        delay = delay_for(attempt, exc)
                        log.warning("retrying %s in %.2fs (%s)", fn.__name__, delay, type(exc).__name__)
                        await (sleep or asyncio.sleep)(delay)

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    if attempt == max_attempts - 1 or not is_retryable(exc, retry_on):
                        raise
                    delay = delay_for(attempt, exc)
                    log.warning("retrying %s in %.2fs (%s)", fn.__name__, delay, type(exc).__name__)
                    (sleep or time.sleep)(delay)

        return wrapper  # type: ignore[return-value]

    return decorator
