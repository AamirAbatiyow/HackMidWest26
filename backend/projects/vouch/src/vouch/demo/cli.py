"""``vouch-demo``: the Friday vendor run end to end - seed, hold, approve, settle.

    vouch-demo                 six structured invoices (same as POST /v1/demo/seed)
    vouch-demo --files         the same six invoices as .eml / PDF / XLSX / PNG / CSV through the intake path
    vouch-demo --xrpl          settle on the XRPL testnet (needs XRPL_WALLET_SEED; see `make xrpl-wallets`)
    vouch-demo --mode live     use the Akamai-hosted LLM for intake quotes, investigators and explanations

Exit code 0 when every invoice lands in its expected lane and the settlement returns transaction ids.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from ..cards import PaymentCard
from ..domain import CardStatus, Lane

# vendor -> (lane, frontend status at intake, frontend risk at intake)
EXPECTED: dict[str, tuple[Lane, str, str]] = {
    "Prairie Packaging Supply": (Lane.FAST_PAY, "vouched", "none"),
    "Rheinland Gewürze GmbH": (Lane.STANDARD, "vouched", "none"),
    "Bao Lin Ceramics": (Lane.STANDARD, "vouched", "none"),
    "Sonora Fresh Produce": (Lane.HOLD, "verify", "changed_bank"),
    "Midwest Facility Services": (Lane.HOLD, "quick_check", "duplicate_or_split"),
    "Apex Global Trading LLC": (Lane.HOLD, "verify", "unrecognized_vendor"),
}


def _check_intake(payments: list[dict]) -> list[str]:
    """Every demo vendor must be resolved by name and land in its expected lane / status / risk."""
    problems: list[str] = []
    by_name = {p["vendor"]["name"]: p for p in payments}
    for name, (lane, status, risk) in EXPECTED.items():
        p = by_name.get(name)
        if p is None:
            problems.append(f"{name}: not found (vendor not resolved?)")
            continue
        got = (p["lane"], p["status"], p["risk"])
        if got != (lane.value, status, risk):
            problems.append(f"{name}: expected {(lane.value, status, risk)} got {got}")
    return problems


def _row(p: dict) -> str:
    top = p["lime"][0]["label"] if p.get("lime") else "-"
    return (
        f"  {p['vendor']['name']:28} {p['invoice_number']:14} {p['amount']:>10,.2f}  "
        f"lane={p['lane'] or '-':9} status={p['status']:12} lifecycle={p['lifecycle']:9} risk={p['risk']:20} "
        f"trust={p['trust_score']:3}  match={p['vendor']['match']:9} sender={','.join((p.get('sender') or {}).get('flags') or []) or 'ok'}\n"
        f"      {p['reason'][:140]}\n      top factor: {top}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the Vouch demo end to end: seed, hold, approve, settle.")
    ap.add_argument("--mode", choices=["auto", "live", "offline"], default="auto", help="LLM mode")
    ap.add_argument("--files", action="store_true", help="feed the six invoices as files/emails through intake")
    ap.add_argument("--xrpl", action="store_true", help="SETTLEMENT_ADAPTER=xrpl (real testnet transactions)")
    ap.add_argument("--db", default=None, help="SQLAlchemy URL (default: DATABASE_URL or local SQLite)")
    ap.add_argument("--json", action="store_true", help="print the payments as JSON at the end")
    ap.add_argument("--keep", action="store_true", help="do not forget earlier runs first")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )
    if args.xrpl:
        os.environ["SETTLEMENT_ADAPTER"] = "xrpl"

    from ..config import get_settings, reset_settings_cache
    from ..service import VouchService

    reset_settings_cache()
    settings = get_settings()
    out = sys.stderr if args.json else sys.stdout
    service = VouchService(
        settings, llm_mode=None if args.mode == "auto" else args.mode, database_url=args.db, seed_demo=False
    )
    e = service.engine
    print(
        f"Vouch demo · llm={e.llm.mode}/{e.llm.provider()} · scorer={getattr(e.scorer(), 'name', '?')} · "
        f"settlement={e.adapter.name} ({e.adapter.network}) · db={service.store.backend} · policy={service.info()['policy_mode']}",
        file=out,
    )

    # 1. seed -------------------------------------------------------------------------------------------
    if not args.keep:
        service.reset(run_demo=False)
    if args.files:
        from .samples import build_samples

        print("\n[1] intake: six invoices as .eml / PDF / XLSX / PNG / CSV", file=out)
        runs = [service.intake(s.request, label=f"demo file: {s.key}") for s in build_samples()]
    else:
        print("\n[1] intake: six structured invoices (POST /v1/demo/seed)", file=out)
        runs = [service.seed(run_demo=True)]
    payments = service.payments()
    print(f"    {len(payments)} payment cards · runs: {', '.join(r.id for r in runs if r)}", file=out)
    for p in payments:
        print(_row(p), file=out)
    intake_problems = _check_intake(payments)
    for problem in intake_problems:
        print(f"    !! {problem}", file=out)

    def by_vendor(prefix: str) -> dict:
        return next(p for p in service.payments() if p["vendor"]["name"].startswith(prefix))

    def card(pid: str) -> PaymentCard:
        return service.find(pid)[1]

    # 2. hold --------------------------------------------------------------------------------------------
    rhein = by_vendor("Rheinland")
    print("\n[2] hold: owner holds Rheinland for a quick check", file=out)
    p = service.hold(rhein["id"], "Double-check the 2/10 discount before paying", "Dana Whitfield")
    print(f"    -> lifecycle={p['lifecycle']} status={p['status']} reasons={p['policy_reasons']}", file=out)

    # 3. approve -----------------------------------------------------------------------------------------
    print("\n[3] approve: owner releases the hold and approves Rheinland + Bao Lin", file=out)
    for prefix in ("Rheinland", "Bao Lin"):
        p = service.approve(by_vendor(prefix)["id"], "Checked, pay it", "Dana Whitfield")
        print(f"    {p['vendor']['name']:28} -> lifecycle={p['lifecycle']} status={p['status']}", file=out)
    sonora = by_vendor("Sonora")
    try:
        service.settle([sonora["id"]])
        print("    !! Sonora settled while on hold", file=out)
        held_ok = False
    except Exception as exc:
        held_ok = True
        print(f"    Sonora stays on hold: {str(exc)[:150]}", file=out)

    # 4. settle ------------------------------------------------------------------------------------------
    print("\n[4] settle: one batch for the approved cards (same approval interrupt + policy re-check)", file=out)
    ids = [by_vendor("Rheinland")["id"], by_vendor("Bao Lin")["id"]]
    receipt = service.settle(ids, "now", "Dana Whitfield", "Friday batch")
    print(
        f"    batch {receipt['batch_id']} · {receipt['network']} · total ${receipt['total_amount']:,.2f}\n"
        f"    tx {receipt['tx_id']}\n    {receipt['explorer_url']}",
        file=out,
    )
    for line in receipt["lines"]:
        print(f"      {line['vendor_name']:28} {line['invoice_number']:14} ${line['amount']:>9,.2f}  {line['tx_id']}  {line['explorer_url'] or ''}", file=out)

    # 5. summary -----------------------------------------------------------------------------------------
    print("\n[5] queue after the run", file=out)
    final = service.payments()
    for p in final:
        print(f"  {p['vendor']['name']:28} lane={p['lane'] or '-':9} lifecycle={p['lifecycle']:9} status={p['status']:12} tx={p['settlement_tx_id'] or '-'}", file=out)
    snap = e.llm.snapshot()
    print(
        f"\nllm: mode={snap['mode']} agent_calls={snap.get('agent_calls')} fallbacks={snap.get('fallbacks_to_template')} "
        f"requests={snap['requests']['requests']} throttled={snap['requests']['throttled']} p95={snap['p95_ms']}ms · "
        f"audit store: {service.store.counts()}",
        file=out,
    )
    if args.json:
        print(json.dumps(final, indent=2, default=str))

    bad = [
        (p["vendor"]["name"], p["lane"], EXPECTED[p["vendor"]["name"]][0].value)
        for p in final
        if p["vendor"]["name"] in EXPECTED
        and p["lane"] != EXPECTED[p["vendor"]["name"]][0].value
        and card(p["id"]).status != CardStatus.PAID
    ]
    paid = [p for p in final if p["lifecycle"] == "settled"]
    ok = (
        not intake_problems
        and not bad
        and held_ok
        and len(paid) >= 3
        and all(line["tx_id"] for line in receipt["lines"])
    )
    if bad:
        print("unexpected lanes:", bad, file=out)
    print("\nRESULT:", "OK" if ok else "FAILED", file=out)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
