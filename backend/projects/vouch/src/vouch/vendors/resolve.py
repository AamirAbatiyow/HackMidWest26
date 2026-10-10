"""Vendor resolution: known / new / uncertain.

Order of evidence: tax id → email domain → fuzzy name (+ address) with embeddings → bank
account. Identifiers are compared in code; embeddings only rank name candidates.
"""

from __future__ import annotations

import logging
from typing import Protocol

from rapidfuzz import fuzz

from ..models import ParsedInvoice, Vendor, VendorCandidate, VendorResolution
from .directory import VendorDirectory, normalize_address, normalize_name
from .embeddings import EmbeddingIndex

log = logging.getLogger(__name__)

KNOWN_FUZZY = 90.0
UNCERTAIN_FUZZY = 72.0
KNOWN_COSINE = 0.90
UNCERTAIN_COSINE = 0.80


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]] | None: ...


def vendor_embedding_text(v: Vendor) -> str:
    return f"{v.name} | {v.address or ''} | {v.city} {v.country}".strip()


def index_vendors(directory: VendorDirectory, embedder: Embedder | None, index: EmbeddingIndex) -> int:
    """Embed every vendor (16 inputs per request, cached by the embedder). Returns count indexed."""
    if embedder is None:
        return 0
    vendors = directory.all()
    texts = [vendor_embedding_text(v) for v in vendors]
    vectors = embedder.embed(texts)
    if not vectors:
        return 0
    for v, vec in zip(vendors, vectors, strict=False):
        index.upsert(v.id, v.name, vec)
    return len(vectors)


def resolve_vendor(
    parsed: ParsedInvoice,
    directory: VendorDirectory,
    *,
    sender_domain: str | None = None,
    embedder: Embedder | None = None,
    index: EmbeddingIndex | None = None,
) -> VendorResolution:
    f = parsed.fields
    claimed = (f.vendor_name or "").strip() or "Unknown vendor"
    res = VendorResolution(status="new", vendor_name=claimed)

    def known(v: Vendor, how: str, conf: float) -> VendorResolution:
        res.status = "known"
        res.vendor_id = v.id
        res.vendor_name = v.name
        res.matched_on.append(how)
        res.confidence = max(res.confidence, conf)
        return res

    v = directory.by_tax_id(parsed.tax_id_digits)
    if v:
        return known(v, "tax_id", 0.98)

    for dom in (parsed.email_domain, sender_domain):
        v = directory.by_domain(dom)
        if v:
            return known(v, "email_domain", 0.92)

    # Fuzzy name and address.
    candidates: dict[str, VendorCandidate] = {}
    qn = normalize_name(claimed)
    qa = normalize_address(f.vendor_address)
    for cand in directory.all():
        score = fuzz.token_set_ratio(qn, normalize_name(cand.name)) if qn else 0.0
        if qa and cand.address and normalize_address(cand.address) == qa:
            score = max(score, 88.0)
        if score >= UNCERTAIN_FUZZY:
            candidates[cand.id] = VendorCandidate(
                vendor_id=cand.id, name=cand.name, score=round(score / 100, 3), matched_on="name_fuzzy"
            )

    if embedder is not None and index is not None and qn:
        try:
            vec = embedder.embed([f"{claimed} | {f.vendor_address or ''} | "])
        except Exception as exc:  # pragma: no cover - network
            log.warning("embedding failed: %s", exc)
            vec = None
        if vec:
            res.embedding_used = True
            for key, label, sim in index.search(vec[0], k=5):
                if sim >= UNCERTAIN_COSINE:
                    prev = candidates.get(key)
                    if prev is None or sim > prev.score:
                        candidates[key] = VendorCandidate(
                            vendor_id=key, name=label, score=round(sim, 3), matched_on="name_embedding"
                        )
    ranked = sorted(candidates.values(), key=lambda c: c.score, reverse=True)
    res.candidates = ranked[:5]
    if ranked:
        top = ranked[0]
        threshold = KNOWN_COSINE if top.matched_on == "name_embedding" else KNOWN_FUZZY / 100
        if top.score >= threshold:
            cand = directory.get(top.vendor_id)
            if cand:
                known(cand, top.matched_on, top.score)
        elif top.score >= (UNCERTAIN_COSINE if top.matched_on == "name_embedding" else UNCERTAIN_FUZZY / 100):
            res.status = "uncertain"
            res.confidence = top.score
            res.matched_on.append(top.matched_on)
            res.notes.append(f"name resembles {top.name} ({top.score:.2f}); confirm before paying")

    # Bank account is the last signal: it is strong but shared accounts are exactly what fraud rings do.
    bank_matches = directory.by_bank_account(parsed.bank_account_digits)
    if bank_matches:
        if res.status == "known" and res.vendor_id in {b.id for b in bank_matches}:
            res.matched_on.append("bank_account")
            res.confidence = max(res.confidence, 0.97)
        elif (
            res.status != "known"
            and len(bank_matches) == 1
            and fuzz.token_set_ratio(qn, normalize_name(bank_matches[0].name)) >= UNCERTAIN_FUZZY
        ):
            known(bank_matches[0], "bank_account", 0.9)
        else:
            names = ", ".join(sorted(b.name for b in bank_matches))
            res.notes.append(f"bank account on the invoice is on file for: {names}")
    if res.status == "known" and res.vendor_id:
        v = directory.get(res.vendor_id)
        if v and v.payments_completed == 0 and not v.verified_by_callback and not v.registration_verified:
            res.notes.append("vendor is on file but has no completed payments and no verification yet")
    return res
