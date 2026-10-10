"""Vendor-name embedding index: pgvector when DATABASE_URL is Postgres, NumPy in memory otherwise.

Vectors come from the Akamai ``hackathon-embedding`` model (1024 dims) via ``vouch.llm.embeddings``;
the index only stores and searches them.
"""

from __future__ import annotations

import json
import logging
from typing import Protocol

import numpy as np
from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

EMBEDDING_DIM = 1024


class EmbeddingIndex(Protocol):
    backend: str

    def upsert(self, key: str, label: str, vector: list[float]) -> None: ...

    def search(self, vector: list[float], k: int = 5) -> list[tuple[str, str, float]]:
        """Returns (key, label, cosine_similarity) sorted descending."""
        ...

    def __len__(self) -> int: ...


class MemoryEmbeddingIndex:
    backend = "memory"

    def __init__(self) -> None:
        self._keys: list[str] = []
        self._labels: dict[str, str] = {}
        self._vectors: dict[str, np.ndarray] = {}

    def upsert(self, key: str, label: str, vector: list[float]) -> None:
        v = np.asarray(vector, dtype=np.float32)
        norm = np.linalg.norm(v)
        self._vectors[key] = v / norm if norm else v
        self._labels[key] = label
        if key not in self._keys:
            self._keys.append(key)

    def search(self, vector: list[float], k: int = 5) -> list[tuple[str, str, float]]:
        if not self._keys:
            return []
        q = np.asarray(vector, dtype=np.float32)
        qn = np.linalg.norm(q)
        q = q / qn if qn else q
        scored = [(key, self._labels[key], float(np.dot(self._vectors[key], q))) for key in self._keys]
        scored.sort(key=lambda t: t[2], reverse=True)
        return scored[:k]

    def __len__(self) -> int:
        return len(self._keys)


class PgVectorEmbeddingIndex:
    backend = "pgvector"

    def __init__(self, engine: Engine, table: str = "vendor_embeddings") -> None:
        self.engine = engine
        self.table = table
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS {table} ("
                    "key TEXT PRIMARY KEY, label TEXT NOT NULL, "
                    f"embedding vector({EMBEDDING_DIM}) NOT NULL, updated_at TIMESTAMPTZ DEFAULT now())"
                )
            )

    def upsert(self, key: str, label: str, vector: list[float]) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {self.table} (key, label, embedding) VALUES (:k, :l, CAST(:e AS vector)) "
                    "ON CONFLICT (key) DO UPDATE SET label = EXCLUDED.label, embedding = EXCLUDED.embedding, "
                    "updated_at = now()"
                ),
                {"k": key, "l": label, "e": json.dumps([float(x) for x in vector])},
            )

    def search(self, vector: list[float], k: int = 5) -> list[tuple[str, str, float]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    f"SELECT key, label, 1 - (embedding <=> CAST(:e AS vector)) AS sim FROM {self.table} "
                    "ORDER BY embedding <=> CAST(:e AS vector) LIMIT :k"
                ),
                {"e": json.dumps([float(x) for x in vector]), "k": k},
            ).fetchall()
        return [(r[0], r[1], float(r[2])) for r in rows]

    def __len__(self) -> int:
        with self.engine.begin() as conn:
            return int(conn.execute(text(f"SELECT count(*) FROM {self.table}")).scalar() or 0)


def make_embedding_index(engine: Engine | None, is_postgres: bool) -> EmbeddingIndex:
    if engine is not None and is_postgres:
        try:
            return PgVectorEmbeddingIndex(engine)
        except Exception as exc:  # pragma: no cover - depends on server extension
            log.warning("pgvector unavailable (%s); using in-memory index", exc)
    return MemoryEmbeddingIndex()
