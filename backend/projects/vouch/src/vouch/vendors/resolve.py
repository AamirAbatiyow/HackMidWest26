"""Vendor resolution: known / new / uncertain, run as a deterministic graph node right after intake.

Order of evidence: vendor id from the owner's system -> tax id -> non-public email domain -> fuzzy name
(+ address), optionally re-ranked with `hackathon-embedding` vectors -> bank account. Identifiers are
compared in code; embeddings only rank name candidates and can never create a "known" match on their
own above the cosine threshold. An "uncertain" result puts the card on hold for the owner to pick the
record (never an automatic denial).
"""

from __future__ import annotations

import logging
from typing import Protocol

from rapidfuzz import fuzz

from ..contracts import VendorCandidate, VendorClaim, VendorResolution
from ..domain import Vendor
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
    return f"{v.name} | {v.address or ''} | {v.country}".strip()


def index_vendors(directory: VendorDirectory, embedder: Embedder | None, index: EmbeddingIndex) -> int:
    """Embed every vendor (16 inputs per request, cached by the embedder). Returns the count indexed."""
    if embedder is None:
        return 0
    vendors = directory.all()
    texts = [vendor_embedding_text(v) for v in vendors]
    vectors = embedder.embed(texts)
    if not vectors:
        return 0
    for v, vec in zip(vendors, vectors, strict=False):
        if vec:
            index.upsert(v.id, v.name, vec)
    return len(vectors)


def resolve_vendor(
    claim: VendorClaim,
    directory: VendorDirectory,
    *,
    vendor_id: str | None = None,
    sender_domain: str | None = None,
    embedder: Embedder | None = None,
    index: EmbeddingIndex | None = None,
) -> VendorResolution:
    claimed = (claim.name or "").strip() or "unknown vendor"
    res = VendorResolution(status="new", vendor_name=claimed)

    def known(v: Vendor, how: str, conf: float) -> VendorResolution:
        res.status = "known"
        res.vendor_id = v.id
        res.vendor_name = v.name
        if how not in res.matched_on:
            res.matched_on.append(how)
        res.confidence = max(res.confidence, conf)
        return res

    if vendor_id and (v := directory.get(vendor_id)):
        known(v, "vendor_id", 1.0)
    if (v := directory.by_tax_id(claim.tax_id)) and res.status != "known":
        known(v, "tax_id", 0.98)
    elif v and res.vendor_id and v.id != res.vendor_id:
        res.notes.append(f"tax id on the invoice belongs to {v.name}, not the selected vendor")

    if res.status != "known":
        from_email = claim.email.rsplit("@", 1)[-1].lower() if claim.email and "@" in claim.email else None
        for dom in (from_email, sender_domain):
            if dom and (v := directory.by_domain(dom)):
                known(v, "email_domain", 0.92)
                break

    # Fuzzy name and address, with embeddings as a re-ranker.
    candidates: dict[str, VendorCandidate] = {}
    qn = normalize_name(claimed)
    qa = normalize_address(claim.address)
    if res.status != "known" and (qn or qa):
        for cand in directory.all():
            score = fuzz.token_set_ratio(qn, normalize_name(cand.name)) if qn else 0.0
            if qa and cand.address and normalize_address(cand.address) == qa:
                score = max(score, 88.0)
            if score >= UNCERTAIN_FUZZY:
                candidates[cand.id] = VendorCandidate(
                    vendor_id=cand.id, name=cand.name, score=round(score / 100, 3), matched_on="name_fuzzy"
                )
        if embedder is not None and index is not None and qn and len(index) > 0:
            try:
                vec = embedder.embed([f"{claimed} | {claim.address or ''} | "])
            except Exception as exc:  # pragma: no cover - network
                log.warning("embedding failed: %s", exc)
                vec = None
            if vec and vec[0]:
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
    if ranked and res.status != "known":
        top = ranked[0]
        threshold = KNOWN_COSINE if top.matched_on == "name_embedding" else KNOWN_FUZZY / 100
        if top.score >= threshold and (cand := directory.get(top.vendor_id)):
            known(cand, top.matched_on, top.score)
        elif top.score >= (UNCERTAIN_COSINE if top.matched_on == "name_embedding" else UNCERTAIN_FUZZY / 100):
            res.status = "uncertain"
            res.confidence = top.score
            res.matched_on.append(top.matched_on)
            res.notes.append(f"name resembles {top.name} ({top.score:.2f}); confirm before paying")

    # Bank account is the last signal: strong, but shared accounts are exactly what fraud rings do.
    bank_matches = directory.by_bank_account(claim.bank_account)
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
        if v and not v.history and not v.oob_verified:
            res.notes.append("vendor is on file but has no completed payments and no out-of-band verification")
    return res
