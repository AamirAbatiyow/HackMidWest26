"""LLM runtime for the graph's LLM nodes: live (Akamai hosted inference through Strands, Bedrock as an
optional fallback), offline (deterministic templates), or scripted (tests and the red-team suite).

Few calls per run by design (60 rpm shared team key, 32k context, 4096 output): one intake call per
*text* invoice, one investigator call per flagged card, one explainer call per batch of up to 8 cards.
Live calls go through `AkamaiStrandsModel`, whose HTTP client owns the ~45 rpm sliding-window limiter,
usage accounting and 429 back-off, so raw embeddings requests and Strands agents share one budget.
Any failure (429, timeout, bad structured output, provenance rejection) falls back to templates.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

from pydantic import BaseModel

from vouch.config import Settings, get_settings
from vouch.llm.client import AkamaiInference, LlmStats
from vouch.llm.embeddings import AkamaiEmbedder, CacheLookup, CachePersist
from vouch.llm.ratelimit import RateLimiter

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
Mode = Literal["live", "offline", "scripted"]


@dataclass
class LLMStats:
    """Per-role agent accounting (the HTTP-level request stats live in `LlmStats`)."""

    calls: int = 0  # agent invocations
    model_calls: int = 0  # individual model requests (incl. tool round-trips)
    input_tokens: int = 0
    output_tokens: int = 0
    failures: int = 0
    fallbacks: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    by_role: dict[str, dict[str, float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, role: str, input_tokens: int, output_tokens: int, ms: float, ok: bool) -> None:
        with self._lock:
            self.calls += 1
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            self.failures += not ok
            r = self.by_role.setdefault(role, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "ms": 0.0})
            r["calls"] += 1
            r["input_tokens"] += input_tokens
            r["output_tokens"] += output_tokens
            r["ms"] += ms

    def record_model_call(self, ms: float) -> None:
        with self._lock:
            self.model_calls += 1
            self.latencies_ms.append(ms)

    def merge(self, other: LLMStats) -> None:
        with self._lock:
            self.calls += other.calls
            self.model_calls += other.model_calls
            self.input_tokens += other.input_tokens
            self.output_tokens += other.output_tokens
            self.failures += other.failures
            self.fallbacks += other.fallbacks
            self.latencies_ms.extend(other.latencies_ms)
            for role, r in other.by_role.items():
                mine = self.by_role.setdefault(
                    role, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "ms": 0.0}
                )
                for k, v in r.items():
                    mine[k] += v

    def to_dict(self) -> dict[str, Any]:
        lat = sorted(self.latencies_ms)

        def pct(p: float) -> float | None:
            return round(lat[min(int(p * len(lat)), len(lat) - 1)], 1) if lat else None

        return {
            "agent_calls": self.calls,
            "model_calls": self.model_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "failures": self.failures,
            "fallbacks_to_template": self.fallbacks,
            "model_latency_ms": {
                "p50": pct(0.5),
                "p95": pct(0.95),
                "max": round(lat[-1], 1) if lat else None,
            },
            "by_role": self.by_role,
        }


def _call_stats_hook(stats: LLMStats) -> Any:
    from strands.hooks import AfterModelCallEvent, BeforeModelCallEvent, HookProvider, HookRegistry

    class CallStatsHook(HookProvider):
        """Tracing hook: wall-clock latency of every model request (incl. retries and tool round-trips)."""

        def __init__(self) -> None:
            self._t0: list[float] = []

        def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
            registry.add_callback(BeforeModelCallEvent, lambda e: self._t0.append(time.perf_counter()))
            registry.add_callback(AfterModelCallEvent, self._after)

        def _after(self, event: Any) -> None:
            if self._t0:
                stats.record_model_call((time.perf_counter() - self._t0.pop()) * 1000)

    return CallStatsHook()


class LLMRuntime:
    def __init__(
        self,
        mode: Mode,
        model_factory: Callable[[str], Any] | None = None,
        settings: Settings | None = None,
        *,
        embedding_lookup: CacheLookup | None = None,
        embedding_persist: CachePersist | None = None,
    ):
        self.mode = mode
        self.settings = settings or get_settings()
        self.stats = LLMStats()
        self.limiter = RateLimiter(self.settings.llm_rpm)
        self.request_stats = LlmStats()
        self.inference = AkamaiInference(self.settings, self.limiter, self.request_stats)
        self.embedder = AkamaiEmbedder(self.inference, lookup=embedding_lookup, persist=embedding_persist)
        self.model_factory = model_factory or (self._live_model if mode == "live" else None)

    # -- construction ------------------------------------------------------------------------------

    @classmethod
    def from_settings(cls, settings: Settings | None = None, **kw: Any) -> LLMRuntime:
        s = settings or get_settings()
        mode = s.effective_llm_mode
        if mode == "live" and not s.has_llm_key and not cls._bedrock_configured():
            log.warning("VOUCH_LLM_MODE=live but no AKAMAI_INFERENCE_API_KEY (or Bedrock); using templates")
            mode = "offline"
        return cls(mode, settings=s, **kw)

    @classmethod
    def scripted(cls, turns_by_role: dict[str, list[Any]], settings: Settings | None = None) -> LLMRuntime:
        from hm_agents_common.testing import ScriptedModel

        def factory(role: str) -> Any:
            turns = turns_by_role.get(role) or turns_by_role.get("*")
            return ScriptedModel(list(turns)) if turns else None

        return cls("scripted", model_factory=factory, settings=settings)

    @staticmethod
    def _bedrock_configured() -> bool:
        try:
            from hm_llm.settings import get_llm_settings

            return get_llm_settings().bedrock_configured
        except Exception:
            return False

    def _live_model(self, role: str) -> Any:
        """A fresh Strands model per agent (the async client must stay on one event loop)."""
        if self.inference.configured:
            from vouch.llm.strands_model import AkamaiStrandsModel

            return AkamaiStrandsModel(self.inference)
        from hm_agents_common.model import make_model

        return make_model()  # Bedrock (LLM_PROVIDER / BEDROCK_MODEL_ID) when no Akamai key is present

    # -- introspection -----------------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self.mode != "offline"

    @property
    def live(self) -> bool:
        return self.mode == "live"

    def provider(self) -> str:
        if self.mode != "live":
            return self.mode
        if self.inference.configured:
            return "akamai"
        return "bedrock" if self._bedrock_configured() else "unconfigured"

    @property
    def model_name(self) -> str:
        if self.mode == "live":
            return self.settings.akamai_chat_model if self.inference.configured else "bedrock"
        return "templates (no model)" if self.mode == "offline" else "scripted"

    def embedder_or_none(self) -> AkamaiEmbedder | None:
        return self.embedder if self.live and self.embedder.configured else None

    def snapshot(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "provider": self.provider(),
            "model": self.model_name,
            "embedding_model": self.settings.akamai_embedding_model if self.embedder_or_none() else None,
            "base_url": self.settings.akamai_base_url if self.inference.configured else None,
            "rate_limit": self.limiter.snapshot(),
            "requests": self.request_stats.snapshot(),
            "p50_ms": self.request_stats.percentile(50),
            "p95_ms": self.request_stats.percentile(95),
            "embedding_cache": {"hits": self.embedder.hits, "misses": self.embedder.misses},
            **self.stats.to_dict(),
        }

    # -- the one call shape every LLM node uses ----------------------------------------------------

    def structured(
        self,
        role: str,
        system_prompt: str,
        prompt: str,
        output_model: type[T],
        tools: list[Any] | None = None,
    ) -> T | None:
        """One agent invocation that must end in `output_model`. Returns None on any failure (caller falls back)."""
        if not self.enabled:
            return None
        model = self.model_factory(role) if self.model_factory else None
        if self.mode == "scripted" and model is None:
            return None
        from hm_agents_common.model import make_agent

        t0 = time.perf_counter()
        ok, usage = False, {}
        try:
            agent = make_agent(
                name=f"vouch-{role}",
                system_prompt=system_prompt,
                tools=tools or [],
                model=model,
                hooks=[_call_stats_hook(self.stats)],
                window_size=12,
            )
            result = agent(prompt, structured_output_model=output_model)
            usage = dict(getattr(result.metrics, "accumulated_usage", {}) or {})
            out = result.structured_output
            ok = isinstance(out, output_model)
            return out if ok else None
        except Exception as exc:
            log.warning("LLM role=%s failed: %s", role, exc)
            return None
        finally:
            ms = (time.perf_counter() - t0) * 1000
            self.stats.record(
                role, int(usage.get("inputTokens", 0)), int(usage.get("outputTokens", 0)), ms, ok
            )
