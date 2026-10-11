"""Vendor resolution: tax id / domain / bank / fuzzy name / embeddings → known | uncertain | new."""

from __future__ import annotations

import os

import pytest

from vouch.contracts import VendorClaim
from vouch.demo import demo_vendors
from vouch.vendors import VendorDirectory
from vouch.vendors.embeddings import MemoryEmbeddingIndex, make_embedding_index
from vouch.vendors.resolve import index_vendors, name_similarity, resolve_vendor

DIR = VendorDirectory(demo_vendors())
PRAIRIE = DIR.get("v-prairie")


def test_name_similarity_prefers_exact_over_containment():
    exact = name_similarity("prairie packaging supply", "prairie packaging supply")
    contained = name_similarity("prairie packaging supply", "prairie packaging")
    typo = name_similarity("prairie packaging supply", "prairie packing supplies")
    unrelated = name_similarity("prairie packaging supply", "quantum edge logistics")
    assert exact == 100.0
    assert 72 <= contained < 100
    assert 72 <= typo < 90
    assert unrelated < 60


def test_resolve_by_tax_id_beats_name():
    claim = VendorClaim(name="PPS Packaging", tax_id=PRAIRIE.tax_id)
    res = resolve_vendor(claim, DIR)
    assert res.status == "known" and res.vendor_id == "v-prairie" and "tax_id" in res.matched_on


def test_resolve_by_sender_domain():
    res = resolve_vendor(VendorClaim(name="Accounts Receivable"), DIR, sender_domain="prairiepackaging.com")
    assert res.status == "known" and res.vendor_id == "v-prairie" and "email_domain" in res.matched_on


def test_resolve_exact_name_is_known_and_bank_confirms():
    res = resolve_vendor(VendorClaim(name="Prairie Packaging Supply", bank_account=PRAIRIE.bank_account), DIR)
    assert res.status == "known" and res.vendor_id == "v-prairie"
    assert "bank_account" in res.matched_on and res.confidence >= 0.97


def test_resolve_near_name_without_identity_is_uncertain_not_known():
    res = resolve_vendor(VendorClaim(name="Prairie Packing Supplies", bank_account="US998877665544"), DIR)
    assert res.status == "uncertain"
    assert res.vendor_id is None, "an uncertain match never inherits the real vendor's identity"
    assert res.candidates and res.candidates[0].vendor_id == "v-prairie"
    assert any("confirm before paying" in n for n in res.notes)


def test_resolve_unknown_vendor_is_new():
    res = resolve_vendor(
        VendorClaim(name="Quantum Edge Logistics", bank_account="GB29NWBK60161331926819"), DIR
    )
    assert res.status == "new" and res.vendor_id is None and not res.candidates


def test_shared_bank_account_is_noted_not_matched():
    shared = [v for v in DIR.all() if len(DIR.by_bank_account(v.bank_account)) > 1]
    assert shared, "the demo world contains a vendor ring sharing one bank account"
    res = resolve_vendor(VendorClaim(name="Totally New Trading", bank_account=shared[0].bank_account), DIR)
    assert res.status == "new"
    assert any("on file for" in n for n in res.notes)


class _ToyEmbedder:
    """Deterministic bag-of-characters embedder standing in for hackathon-embedding."""

    dim = 64

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            vec = [0.0] * self.dim
            for i, ch in enumerate(t.lower()):
                if ch.isalnum():
                    vec[(ord(ch) * 7 + i // 3) % self.dim] += 1.0
            out.append(vec)
        return out


def test_embedding_index_reranks_candidates_in_memory():
    index = MemoryEmbeddingIndex()
    n = index_vendors(DIR, _ToyEmbedder(), index)
    assert n == len(DIR) and len(index) == len(DIR)
    res = resolve_vendor(
        VendorClaim(name="Prairie Packaging Supply Co"), DIR, embedder=_ToyEmbedder(), index=index
    )
    assert res.embedding_used
    assert res.status in ("known", "uncertain")
    assert res.candidates[0].vendor_id == "v-prairie"


def test_make_embedding_index_falls_back_to_memory_without_postgres():
    assert make_embedding_index(None, False).backend == "memory"


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith(("postgres", "postgresql")),
    reason="pgvector index needs DATABASE_URL pointing at Postgres",
)
def test_pgvector_index_roundtrip():
    from vouch.audit import AuditStore
    from vouch.config import Settings

    store = AuditStore.open(Settings().effective_database_url)
    assert store.backend == "postgres"
    index = make_embedding_index(store.engine, True)
    assert index.backend == "pgvector"
    index.upsert("t-1", "Prairie Packaging Supply", [1.0] + [0.0] * 1023)
    index.upsert("t-2", "Quantum Edge", [0.0, 1.0] + [0.0] * 1022)
    hits = index.search([1.0] + [0.0] * 1023, k=2)
    assert hits[0][0] == "t-1" and hits[0][2] > hits[1][2]
