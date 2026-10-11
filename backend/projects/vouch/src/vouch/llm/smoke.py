"""``vouch-smoke-llm`` / ``make smoke-llm``: prove the Akamai-hosted LLM path end to end.

Runs live when ``AKAMAI_INFERENCE_API_KEY`` is set (chat via the Strands agent with structured output,
embeddings via ``hackathon-embedding``) and skips cleanly (exit 0) otherwise. Never prints the key.
"""

from __future__ import annotations

import math
import sys
import time

SAMPLE = (
    "From: Prairie Packaging Supply\nInvoice No: PPS-2207\nInvoice Date: 2026-10-07\n"
    "PO: PO-48790\nTotal Due: $1,180.00\nDue Date: 2026-10-21\nBank account: US021000089912\n"
)


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def main() -> None:
    from vouch.agents import INTAKE_PROMPT, IntakeExtraction
    from vouch.config import get_settings
    from vouch.llm import LLMRuntime

    s = get_settings()
    if not s.has_llm_key:
        print("SKIP smoke-llm: AKAMAI_INFERENCE_API_KEY is not set (templates are used; nothing to call)")
        raise SystemExit(0)
    runtime = LLMRuntime.from_settings(s.model_copy(update={"llm_mode": "live"}))
    print(
        f"endpoint {s.akamai_base_url} · chat {s.akamai_chat_model} · embeddings {s.akamai_embedding_model}"
    )
    print(f"client limiter {s.llm_rpm} rpm · max_tokens {s.llm_max_tokens} · provider {runtime.provider()}")
    ok = True

    # 1. connectivity probe (GET /models) ------------------------------------------------------------
    t0 = time.perf_counter()
    alive, detail = runtime.inference.probe()
    print(f"[1] probe: {'ok' if alive else 'FAIL'} · {detail} · {int((time.perf_counter() - t0) * 1000)} ms")
    ok &= alive

    # 2. structured chat through the Strands agent -------------------------------------------------
    t0 = time.perf_counter()
    ext = runtime.structured("intake", INTAKE_PROMPT, f"INVOICE TEXT:\n{SAMPLE}", IntakeExtraction)
    ms = int((time.perf_counter() - t0) * 1000)
    if ext is None:
        print(f"[2] chat: FAIL (no structured output) · {ms} ms · stats {runtime.stats.to_dict()}")
        ok = False
    else:
        verbatim = ext.amount_quote.strip() in SAMPLE and (ext.due_date_quote or "").strip() in SAMPLE
        print(
            f"[2] chat: ok · {ms} ms · vendor={ext.vendor_name!r} amount_quote={ext.amount_quote!r} "
            f"due={ext.due_date_quote!r} verbatim_in_source={verbatim}"
        )
        ok &= verbatim

    # 3. embeddings -----------------------------------------------------------------------------------
    t0 = time.perf_counter()
    vecs = runtime.embedder.embed(
        ["Prairie Packaging Supply", "Prairie Packaging Supply Co.", "Sonora Fresh Produce"]
    )
    ms = int((time.perf_counter() - t0) * 1000)
    if not vecs or not all(vecs):
        print(f"[3] embeddings: FAIL · {ms} ms")
        ok = False
    else:
        near, far = _cos(vecs[0], vecs[1]), _cos(vecs[0], vecs[2])
        print(f"[3] embeddings: ok · dim={len(vecs[0])} · {ms} ms · cos(near)={near:.3f} cos(far)={far:.3f}")
        ok &= len(vecs[0]) == 1024 and near > far

    snap = runtime.snapshot()
    print(
        f"requests={snap['requests']['requests']} errors={snap['requests']['errors']} "
        f"throttled={snap['requests']['throttled']} p95={snap['p95_ms']} ms · rate_limit={snap['rate_limit']}"
    )
    print("RESULT:", "OK" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
