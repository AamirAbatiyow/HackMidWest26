"""``vouch-demo``: run the eight-invoice scenario through the pipeline and print the queue."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from ..config import get_settings
from ..service import VouchService
from .scenario import seed_demo, summarize


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the Vouch demo scenario.")
    ap.add_argument(
        "--mode",
        choices=["auto", "live", "template"],
        default="auto",
        help="LLM mode (auto = live when the key is set)",
    )
    ap.add_argument("--db", default=None, help="SQLAlchemy URL (default: DATABASE_URL or local SQLite)")
    ap.add_argument("--json", action="store_true", help="print the payments as JSON")
    ap.add_argument("--keep", action="store_true", help="do not clear existing payments first")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )
    settings = get_settings()
    mode = None if args.mode == "auto" else args.mode
    service = VouchService(settings, llm_mode=mode, database_url=args.db)
    print(
        f"Vouch demo · llm_mode={service.llm.mode} · model={service.llm.model_name} · db={service.store.backend}",
        file=sys.stderr if args.json else sys.stdout,
    )
    results = asyncio.run(seed_demo(service, reset=not args.keep))
    if args.json:
        print(json.dumps([p.api_view() for _, p in results], indent=2, default=str))
    else:
        print(summarize(results))
        snap = service.llm.snapshot()
        print(
            f"\nllm requests={snap['stats']['requests']} throttled={snap['stats']['throttled']} p50={snap['p50_ms']}ms p95={snap['p95_ms']}ms "
            f"tokens={snap['stats']['prompt_tokens_today']}+{snap['stats']['completion_tokens_today']} · audit {service.store.counts()}"
        )
    bad = [(s, p) for s, p in results if p.status != s.expected_status or p.risk != s.expected_risk]
    raise SystemExit(1 if bad else 0)
