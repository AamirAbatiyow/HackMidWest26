"""OpenAI-compatible clients for Akamai hosted inference, with the shared rate budget and
request statistics wired in at the HTTP layer (so chat, structured output and embeddings are
all covered, including Strands' ``structured_output`` which bypasses agent hooks)."""

from __future__ import annotations

import logging
import statistics
import threading
import time
from dataclasses import dataclass, field
from datetime import date

import httpx
import openai

from ..config import Settings
from .ratelimit import RateLimiter

log = logging.getLogger(__name__)


@dataclass
class LlmStats:
    requests: int = 0
    errors: int = 0
    throttled: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    day: date = field(default_factory=date.today)
    latencies_ms: list[int] = field(default_factory=list)
    last_error: str | None = None
    last_model: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _roll_day(self) -> None:
        today = date.today()
        if today != self.day:
            self.day = today
            self.prompt_tokens = 0
            self.completion_tokens = 0

    def record_request(self, latency_ms: int, status: int) -> None:
        with self._lock:
            self._roll_day()
            self.requests += 1
            self.latencies_ms.append(latency_ms)
            if len(self.latencies_ms) > 500:
                del self.latencies_ms[: len(self.latencies_ms) - 500]
            if status == 429:
                self.throttled += 1
            elif status >= 400:
                self.errors += 1

    def record_usage(self, prompt: int, completion: int, model: str | None = None) -> None:
        with self._lock:
            self._roll_day()
            self.prompt_tokens += int(prompt or 0)
            self.completion_tokens += int(completion or 0)
            if model:
                self.last_model = model

    def percentile(self, p: float) -> int | None:
        with self._lock:
            if not self.latencies_ms:
                return None
            xs = sorted(self.latencies_ms)
            if len(xs) == 1:
                return xs[0]
            q = statistics.quantiles(xs, n=100, method="inclusive")
            return int(q[min(99, max(0, int(p) - 1))])

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "requests": self.requests,
                "errors": self.errors,
                "throttled": self.throttled,
                "prompt_tokens_today": self.prompt_tokens,
                "completion_tokens_today": self.completion_tokens,
                "last_error": self.last_error,
                "last_model": self.last_model,
            }


class AkamaiInference:
    """Factory for sync/async OpenAI clients pointed at the Akamai workshop endpoint."""

    def __init__(
        self, settings: Settings, limiter: RateLimiter | None = None, stats: LlmStats | None = None
    ) -> None:
        self.settings = settings
        self.limiter = limiter or RateLimiter(settings.llm_rpm)
        self.stats = stats or LlmStats()
        self._sync: openai.OpenAI | None = None

    @property
    def configured(self) -> bool:
        return bool(self.settings.akamai_api_key)

    # ---- httpx hooks -------------------------------------------------------
    async def _before_async(self, request: httpx.Request) -> None:
        await self.limiter.acquire_async()
        request.extensions["vouch_t0"] = time.monotonic()

    def _before_sync(self, request: httpx.Request) -> None:
        self.limiter.acquire()
        request.extensions["vouch_t0"] = time.monotonic()

    def _record_usage_from_body(self, response: httpx.Response) -> None:
        if response.status_code != 200 or "json" not in response.headers.get("content-type", ""):
            return
        try:
            body = response.json()
        except Exception:
            return
        usage = body.get("usage") if isinstance(body, dict) else None
        if isinstance(usage, dict):
            self.stats.record_usage(
                usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), body.get("model")
            )

    def _after(self, response: httpx.Response) -> None:
        t0 = response.request.extensions.get("vouch_t0")
        latency = int((time.monotonic() - t0) * 1000) if t0 else 0
        self.stats.record_request(latency, response.status_code)
        try:
            response.read()
            self._record_usage_from_body(response)
        except Exception:  # pragma: no cover - streaming bodies
            pass
        self._handle_errors(response)

    async def _after_async(self, response: httpx.Response) -> None:
        t0 = response.request.extensions.get("vouch_t0")
        latency = int((time.monotonic() - t0) * 1000) if t0 else 0
        self.stats.record_request(latency, response.status_code)
        try:
            await response.aread()
            self._record_usage_from_body(response)
        except Exception:  # pragma: no cover - streaming bodies
            pass
        self._handle_errors(response)

    def _handle_errors(self, response: httpx.Response) -> None:
        if response.status_code == 429:
            reset = response.headers.get("x-ratelimit-reset") or response.headers.get("retry-after")
            try:
                seconds = float(reset) if reset else 5.0
            except ValueError:
                seconds = 5.0
            self.limiter.penalize(min(seconds, 60.0))
            self.stats.last_error = f"429 from inference (reset in {seconds:.0f}s)"
            log.warning("Akamai inference throttled; pausing %.0fs", seconds)
        elif response.status_code >= 400:
            self.stats.last_error = f"HTTP {response.status_code} from inference"

    # ---- clients -----------------------------------------------------------
    def async_client(self) -> openai.AsyncOpenAI:
        http = httpx.AsyncClient(
            timeout=self.settings.llm_timeout_s,
            event_hooks={"request": [self._before_async], "response": [self._after_async]},
        )
        return openai.AsyncOpenAI(
            base_url=self.settings.akamai_base_url,
            api_key=self.settings.akamai_api_key or "missing",
            max_retries=self.settings.llm_max_retries,
            http_client=http,
        )

    def sync_client(self) -> openai.OpenAI:
        if self._sync is None:
            http = httpx.Client(
                timeout=self.settings.llm_timeout_s,
                event_hooks={"request": [self._before_sync], "response": [self._after]},
            )
            self._sync = openai.OpenAI(
                base_url=self.settings.akamai_base_url,
                api_key=self.settings.akamai_api_key or "missing",
                max_retries=self.settings.llm_max_retries,
                http_client=http,
            )
        return self._sync

    def probe(self) -> tuple[bool, str]:
        """Cheap reachability check used by /health (one request)."""
        if not self.configured:
            return False, "AKAMAI_INFERENCE_API_KEY not set"
        try:
            t0 = time.monotonic()
            models = self.sync_client().models.list()
            ids = [m.id for m in models.data][:5]
            return (
                True,
                f"{self.settings.akamai_base_url} · models {ids} · {int((time.monotonic() - t0) * 1000)} ms",
            )
        except Exception as exc:
            return False, f"{type(exc).__name__}: {str(exc)[:120]}"
