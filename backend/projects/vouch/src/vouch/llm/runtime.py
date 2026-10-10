"""One object that owns the LLM mode, the Akamai clients, the Strands model and the embedder."""

from __future__ import annotations

import logging

from ..config import LlmMode, Settings
from .client import AkamaiInference, LlmStats
from .embeddings import AkamaiEmbedder, CacheLookup, CachePersist
from .ratelimit import RateLimiter
from .reader import LlmReader
from .strands_model import AkamaiStrandsModel
from .writer import LlmWriter

log = logging.getLogger(__name__)


class LlmRuntime:
    def __init__(
        self,
        settings: Settings,
        *,
        mode: LlmMode | None = None,
        embedding_lookup: CacheLookup | None = None,
        embedding_persist: CachePersist | None = None,
    ) -> None:
        self.settings = settings
        self.mode: LlmMode = mode or settings.llm_mode
        if self.mode == "live" and not settings.has_llm_key:
            log.warning("llm_mode=live requested but AKAMAI_INFERENCE_API_KEY is empty; using template mode")
            self.mode = "template"
        self.limiter = RateLimiter(settings.llm_rpm)
        self.stats = LlmStats()
        self.inference = AkamaiInference(settings, self.limiter, self.stats)
        self.embedder = AkamaiEmbedder(self.inference, lookup=embedding_lookup, persist=embedding_persist)
        self._model: AkamaiStrandsModel | None = None

    @property
    def live(self) -> bool:
        return self.mode == "live"

    @property
    def model_name(self) -> str:
        return self.settings.akamai_chat_model if self.live else "template (no model)"

    def model(self) -> AkamaiStrandsModel:
        """A fresh Strands model per call site (the async client must stay on one event loop)."""
        return AkamaiStrandsModel(self.inference)

    def reader(self) -> LlmReader | None:
        return LlmReader(self.model()) if self.live else None

    def writer(self) -> LlmWriter | None:
        return LlmWriter(self.model()) if self.live else None

    def embedder_or_none(self) -> AkamaiEmbedder | None:
        return self.embedder if self.embedder.configured else None

    def snapshot(self) -> dict:
        return {
            "mode": self.mode,
            "model": self.model_name,
            "embedding_model": self.settings.akamai_embedding_model if self.embedder.configured else None,
            "base_url": self.settings.akamai_base_url,
            "rate_limit": self.limiter.snapshot(),
            "stats": self.stats.snapshot(),
            "p50_ms": self.stats.percentile(50),
            "p95_ms": self.stats.percentile(95),
            "embedding_cache": {"hits": self.embedder.hits, "misses": self.embedder.misses},
        }
