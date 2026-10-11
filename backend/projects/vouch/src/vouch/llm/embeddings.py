"""Embeddings from Akamai ``hackathon-embedding`` (1024 dims, ≤16 inputs per request) with a
content-hash cache (in memory, optionally persisted through a callback)."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable

from .client import AkamaiInference

log = logging.getLogger(__name__)

BATCH = 16
CachePersist = Callable[[str, str, list[float]], None]
CacheLookup = Callable[[str], list[float] | None]


def text_key(text: str, model: str) -> str:
    return hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()


class AkamaiEmbedder:
    def __init__(
        self,
        inference: AkamaiInference,
        *,
        lookup: CacheLookup | None = None,
        persist: CachePersist | None = None,
    ) -> None:
        self.inference = inference
        self.model = inference.settings.akamai_embedding_model
        self._cache: dict[str, list[float]] = {}
        self._lookup = lookup
        self._persist = persist
        self.hits = 0
        self.misses = 0

    @property
    def configured(self) -> bool:
        return self.inference.configured

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        if not self.configured or not texts:
            return None
        out: list[list[float] | None] = [None] * len(texts)
        todo: list[int] = []
        for i, t in enumerate(texts):
            key = text_key(t, self.model)
            vec = self._cache.get(key)
            if vec is None and self._lookup is not None:
                vec = self._lookup(key)
                if vec is not None:
                    self._cache[key] = vec
            if vec is not None:
                out[i] = vec
                self.hits += 1
            else:
                todo.append(i)
        client = self.inference.sync_client()
        for start in range(0, len(todo), BATCH):
            chunk = todo[start : start + BATCH]
            try:
                resp = client.embeddings.create(model=self.model, input=[texts[i] for i in chunk])
            except Exception as exc:
                log.warning("embedding request failed: %s", exc)
                return None
            for i, item in zip(chunk, resp.data, strict=False):
                vec = [float(x) for x in item.embedding]
                out[i] = vec
                key = text_key(texts[i], self.model)
                self._cache[key] = vec
                self.misses += 1
                if self._persist is not None:
                    try:
                        self._persist(key, texts[i], vec)
                    except Exception as exc:  # pragma: no cover
                        log.debug("embedding persist failed: %s", exc)
        return [v if v is not None else [] for v in out]
