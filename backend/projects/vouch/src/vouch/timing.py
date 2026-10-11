"""Lightweight timing instrumentation: ring buffer for rolling p50/p95 and a timing decorator.

Usage:
    from vouch.timing import TIMING, timed

    # As a decorator
    @timed("reader")
    def read_invoice(data): ...

    # As a context manager
    with timed("scorer"):
        score = model.predict(features)

    # Query latencies
    TIMING.p50("reader")  # -> ms or None
    TIMING.all_stats()    # -> {"reader": {"p50": 12, "p95": 45, "count": 100}, ...}
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable)

DEFAULT_RING_SIZE = 200


@dataclass
class RingStats:
    """Per-step latency ring buffer with p50/p95 calculation."""

    name: str
    max_size: int = DEFAULT_RING_SIZE
    _samples: deque[float] = field(default_factory=lambda: deque(maxlen=DEFAULT_RING_SIZE))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self._samples = deque(maxlen=self.max_size)

    def record(self, ms: float) -> None:
        with self._lock:
            self._samples.append(ms)

    def p50(self) -> float | None:
        return self._percentile(0.5)

    def p95(self) -> float | None:
        return self._percentile(0.95)

    def count(self) -> int:
        with self._lock:
            return len(self._samples)

    def latest(self) -> float | None:
        with self._lock:
            return self._samples[-1] if self._samples else None

    def _percentile(self, p: float) -> float | None:
        with self._lock:
            if not self._samples:
                return None
            sorted_samples = sorted(self._samples)
            idx = int(len(sorted_samples) * p)
            idx = min(idx, len(sorted_samples) - 1)
            return round(sorted_samples[idx], 2)

    def stats(self) -> dict:
        return {
            "p50": self.p50(),
            "p95": self.p95(),
            "count": self.count(),
            "latest": self.latest(),
        }


@dataclass
class TimingRegistry:
    """Global registry of timing ring buffers per pipeline step."""

    ring_size: int = DEFAULT_RING_SIZE
    _rings: dict[str, RingStats] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _get(self, name: str) -> RingStats:
        with self._lock:
            if name not in self._rings:
                self._rings[name] = RingStats(name, self.ring_size)
            return self._rings[name]

    def record(self, name: str, ms: float) -> None:
        self._get(name).record(ms)

    def p50(self, name: str) -> float | None:
        return self._get(name).p50()

    def p95(self, name: str) -> float | None:
        return self._get(name).p95()

    def stats(self, name: str) -> dict:
        return self._get(name).stats()

    def all_stats(self) -> dict[str, dict]:
        with self._lock:
            names = list(self._rings.keys())
        return {name: self.stats(name) for name in names}

    def reset(self, name: str) -> None:
        """Drop one ring (its next sample starts it again)."""
        with self._lock:
            self._rings.pop(name, None)

    def clear(self) -> None:
        with self._lock:
            self._rings.clear()


TIMING = TimingRegistry()


@contextmanager
def timed(step: str, registry: TimingRegistry | None = None) -> Generator[None, None, None]:
    """Context manager that records elapsed time in milliseconds to the registry.

    Safe: catches all exceptions from the timing machinery itself.
    """
    reg = registry or TIMING
    t0 = time.perf_counter()
    try:
        yield
    finally:
        try:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            reg.record(step, elapsed_ms)
        except Exception:
            pass


@contextmanager
def card_step(card: Any, step: str) -> Generator[None, None, None]:
    """Record the wall-clock milliseconds one orchestrator step spent on *one* card.

    Writes to ``card.step_ms[step]`` (summed when a step runs twice, e.g. policy re-evaluated after an
    owner action) so the payment payload can show per-invoice durations instead of the run-wide node
    time. Never raises: a card without ``step_ms`` is left untouched.
    """
    t0 = time.perf_counter()
    try:
        yield
    finally:
        try:
            ms = (time.perf_counter() - t0) * 1000
            bucket = getattr(card, "step_ms", None)
            if isinstance(bucket, dict):
                bucket[step] = round(bucket.get(step, 0.0) + ms, 3)
        except Exception:
            pass


def timed_decorator(step: str, registry: TimingRegistry | None = None) -> Callable[[F], F]:
    """Decorator that times function execution and records to the registry."""

    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            with timed(step, registry):
                return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


PIPELINE_STEPS = [
    "reader",
    "sender_check",
    "vendor_resolution",
    "detector_amount",
    "detector_bank",
    "detector_duplicate",
    "detector_ring",
    "scorer",
    "policy",
    "writer",
]

INFERENCE_ENDPOINTS = [
    "hackathon-chat",
    "hackathon-embedding",
]

# The engines an intake routing decision can carry (``vouch.decider.classify.Engine``): the Strands
# Decider 2B server, the hackathon chat classifier, or code alone. ``DECIDER_STEP`` is the ring the
# classifier feeds with one sample per answered Decider question.
DECIDER_ENGINES = ["decider", "hackathon-chat", "deterministic"]
DECIDER_STEP = "decider"
