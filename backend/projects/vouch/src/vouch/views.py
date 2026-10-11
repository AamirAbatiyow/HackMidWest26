"""Frontend views: map the engine's `PaymentCard` (lane, kernel checks, model scores + LIME, sender check,
vendor resolution, resolutions, receipts) onto the payment shape the React frontend renders.

The frontend normalizes snake/camelCase and tolerates extra keys, so every view is a superset: the
contract fields first, then the engine's raw facts for the detail panel and for debugging.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from vouch.cards import PaymentCard
from vouch.contracts import iso, utcnow
from vouch.domain import CardStatus, Lane, Vendor
from vouch.engine import Run, VouchEngine
from vouch.policy import (
    R_BANK,
    R_DUPLICATE,
    R_HIGH_RISK,
    R_INJECTION,
    R_KICKBACK,
    R_LIMIT,
    R_LINES,
    R_LLM_AMOUNT,
    R_OCR_MISSING,
    R_OWNER_HOLD,
    R_RING,
    R_SENDER,
    R_SPLIT,
    R_UNKNOWN_VENDOR,
    R_VENDOR_AMBIGUOUS,
)
from vouch.vendors import ring_graph

QUICK_CHECK_REASONS = {R_DUPLICATE, R_SPLIT, R_LINES, R_LLM_AMOUNT, R_LIMIT, R_KICKBACK, R_OCR_MISSING}
BANK_REASONS = {R_BANK}
VENDOR_REASONS = {R_UNKNOWN_VENDOR, R_VENDOR_AMBIGUOUS, R_RING, R_SENDER, R_INJECTION}
IDENTITY_REASONS = BANK_REASONS | VENDOR_REASONS  # "verify before release": identity, not paperwork

_FLAG_LABELS = {
    "no_authentication_results": "Email carried no SPF/DKIM/DMARC results",
    "spf_fail": "SPF failed for the sending domain",
    "spf_softfail": "SPF soft-failed for the sending domain",
    "dkim_fail": "DKIM signature failed",
    "dkim_missing": "No DKIM signature",
    "dmarc_fail": "DMARC failed",
    "dkim_domain_differs_from_from": "DKIM signed by a different domain than From",
    "reply_to_mismatch": "Reply-To points to a different domain than From",
    "lookalike_domain": "Sender domain looks like a known vendor domain",
    "reply_to_lookalike_domain": "Reply-To domain looks like a known vendor domain",
    "freemail_sender": "Sent from a free webmail address",
    "new_sender_for_known_vendor": "Address never used by this vendor before",
    "display_name_mismatch": "Display name does not match the sending domain",
}


def _city(vendor: Vendor | None) -> str:
    if not vendor or not vendor.address:
        return ""
    parts = [p.strip() for p in vendor.address.split(",")]
    return parts[-2] if len(parts) >= 2 else parts[-1]


def _since(vendor: Vendor | None, today: date) -> str:
    if not vendor:
        return today.isoformat()
    return (today - timedelta(days=vendor.created_days_ago)).isoformat()


def vendor_view(vendor: Vendor | None, card: PaymentCard, today: date) -> dict[str, Any]:
    inv = card.invoice
    return {
        "id": vendor.id if vendor else (inv.vendor_id or f"unknown:{card.id}"),
        "name": vendor.name if vendor else inv.vendor_name,
        "city": _city(vendor),
        "country": vendor.country if vendor else "",
        "since": _since(vendor, today),
        "payments_completed": len(vendor.history) if vendor else 0,
        "email": vendor.email if vendor else inv.remit_email,
        "oob_verified": bool(vendor and vendor.oob_verified),
        "match": card.resolution.status if card.resolution else ("known" if vendor else "new"),
        "matched_on": card.resolution.matched_on if card.resolution else [],
    }


def lifecycle_of(card: PaymentCard) -> str:
    if card.status == CardStatus.PAID:
        return "settled"
    if card.status == CardStatus.APPROVED:
        return "approved"
    last = card.resolutions[-1].kind if card.resolutions else None
    if card.status == CardStatus.HOLD and last == "owner_hold":
        return "held"
    if last == "appeal":
        return "appealed"
    if last == "approve" and card.status != CardStatus.FAILED:
        return "approved"
    return "pending"


def vouch_status(card: PaymentCard) -> str:
    if card.status in (CardStatus.PAID, CardStatus.APPROVED, CardStatus.CREDIT):
        return "vouched"
    p = card.policy
    if p is None:
        return "quick_check"
    if p.lane != Lane.HOLD:
        return "vouched"
    reasons = set(p.reasons)
    if reasons & IDENTITY_REASONS:
        return "verify"
    if reasons & QUICK_CHECK_REASONS or reasons == {R_OWNER_HOLD}:
        return "quick_check"
    return "verify"  # model risk alone (R_HIGH_RISK)


def risk_of(card: PaymentCard) -> str:
    p, ch = card.policy, card.checks
    if p is None or p.lane != Lane.HOLD:
        return "none"
    reasons = set(p.reasons)
    if reasons & BANK_REASONS or (card.sender and card.sender.suspicious and card.invoice.bank_account):
        return "changed_bank"
    if reasons & VENDOR_REASONS:
        return "unrecognized_vendor"
    if reasons & {R_DUPLICATE, R_SPLIT} or ch.get("duplicate_of") or ch.get("split_group"):
        return "duplicate_or_split"
    if reasons & QUICK_CHECK_REASONS:
        return "duplicate_or_split"
    if R_HIGH_RISK in reasons:
        return "unrecognized_vendor"
    return "none"


def trust_score(card: PaymentCard) -> int:
    base = card.scores.legitimacy * 100 if card.scores else 50.0
    if card.sender and card.sender.checked:
        base -= card.sender.risk * 25
    if card.resolution and card.resolution.status == "uncertain":
        base -= 10
    p = card.policy
    if card.status == CardStatus.PAID:
        base = max(base, 88)
    elif p and p.lane == Lane.FAST_PAY:
        base = max(base, 92)
    elif p and p.lane == Lane.STANDARD:
        base = max(base, 70)
    elif p and p.lane == Lane.HOLD:
        reasons = set(p.reasons)
        cap = 55 if not (reasons & IDENTITY_REASONS) else 40
        base = max(min(base, cap), 12 if not (reasons & IDENTITY_REASONS) else 4)
    return int(max(0, min(100, round(base))))


def _factor(idx: int, label: str, weight: float, direction: str) -> dict[str, Any]:
    return {
        "id": f"e{idx}",
        "label": label,
        "weight": round(min(1.0, abs(weight)), 3),
        "direction": direction,
    }


def evidence_of(card: PaymentCard) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    n = 0
    if card.scores:
        toward_legit = card.scores.lime_class == "legitimacy"
        for item in card.scores.lime[:6]:
            w = float(item.get("weight", 0.0))
            concern = (w < 0) if toward_legit else (w > 0)
            n += 1
            out.append(
                _factor(
                    n,
                    str(item.get("label") or item.get("feature")),
                    w,
                    "concern" if concern else "reassuring",
                )
            )
    if card.sender and card.sender.checked:
        if card.sender.auth_pass:
            n += 1
            out.append(_factor(n, f"SPF/DKIM/DMARC pass for {card.sender.from_domain}", 0.35, "reassuring"))
        for flag in card.sender.flags[:5]:
            n += 1
            out.append(_factor(n, _FLAG_LABELS.get(flag, flag.replace("_", " ")), 0.5, "concern"))
    if card.resolution:
        r = card.resolution
        if r.status == "known" and r.matched_on:
            n += 1
            out.append(_factor(n, f"Vendor matched on {', '.join(r.matched_on)}", 0.4, "reassuring"))
        elif r.status == "uncertain":
            n += 1
            out.append(_factor(n, "Vendor match is ambiguous (fuzzy name only)", 0.5, "concern"))
        elif r.status == "new":
            n += 1
            out.append(_factor(n, "Vendor is not on the master file", 0.6, "concern"))
    for flag in card.flags[:6]:
        if any(f["label"] == flag for f in out):
            continue
        n += 1
        out.append(_factor(n, flag[0].upper() + flag[1:], 0.45, "concern"))
    ch = card.checks
    if ch.get("vendor_found") and not card.flags and card.vendor:
        n += 1
        out.append(_factor(n, f"{len(card.vendor.history)} prior payments to this vendor", 0.3, "reassuring"))
    return out


def timeline_of(card: PaymentCard, today: date) -> list[dict[str, Any]]:
    v = card.vendor
    events: list[dict[str, Any]] = []
    k = 0
    if v:
        k += 1
        events.append(
            {
                "id": f"t{k}",
                "date": (today - timedelta(days=v.created_days_ago)).isoformat(),
                "title": "Vendor onboarded",
                "detail": f"{v.name} added to the master file"
                + (" · identity verified out-of-band" if v.oob_verified else ""),
                "kind": "onboard",
            }
        )
        for past in sorted(v.history, key=lambda p: -p.days_ago)[-6:]:
            k += 1
            events.append(
                {
                    "id": f"t{k}",
                    "date": (today - timedelta(days=past.days_ago)).isoformat(),
                    "title": f"Paid {past.invoice_number or 'invoice'} · ${past.amount_cents / 100:,.2f}",
                    "detail": f"Invoice {past.invoice_number}"
                    if past.invoice_number
                    else "Prior payment on file",
                    "kind": "payment",
                }
            )
        if v.bank_changed_days_ago is not None:
            k += 1
            events.append(
                {
                    "id": f"t{k}",
                    "date": (today - timedelta(days=v.bank_changed_days_ago)).isoformat(),
                    "title": "Bank details changed on the master file",
                    "detail": "confirmed by call-back to the number on file"
                    if v.bank_change_confirmed_oob
                    else "not yet confirmed out-of-band",
                    "kind": "change",
                }
            )
    for ev in card.timeline:
        name = ev.get("event")
        if name == "intake_decision":
            k += 1
            cost = f"{ev.get('engine')}, {ev.get('latency_ms', 0):.0f} ms, " + (
                f"{int(ev.get('input_tokens') or 0) + int(ev.get('output_tokens') or 0)} tokens"
            )
            verdict = "" if ev.get("accepted") else f" · rejected: {ev.get('error') or ev.get('note')}"
            reason = f" · reason {ev['reason_code']}" if ev.get("reason_code") else ""
            failures = ev.get("validation_errors") or []
            invalid = (
                f" · {len(failures)} output(s) failed schema validation: {str(failures[0]).splitlines()[-1]}"
                if failures
                else ""
            )
            events.append(
                {
                    "id": f"t{k}",
                    "date": ev["at"],
                    "title": f"Decision {ev.get('key')}: {ev.get('answer') or '-'}",
                    "detail": (
                        f"{ev.get('question')} [{', '.join(ev.get('options') or [])}] → {cost}"
                        f"{reason}{invalid}{verdict}"
                    ),
                    "kind": "check",
                }
            )
        elif name == "intake_review_required":
            k += 1
            events.append(
                {
                    "id": f"t{k}",
                    "date": ev["at"],
                    "title": "Intake routing needs the owner (safe default, not paid on a guess)",
                    "detail": f"{ev.get('reason')} · default {ev.get('default')}"
                    + (
                        f" · {ev['validation_failures']} classifier output(s) failed validation"
                        if ev.get("validation_failures")
                        else ""
                    ),
                    "kind": "check",
                }
            )
        elif name == "intake_classified":
            k += 1
            conf = ev.get("confidence")
            calls = int(ev.get("decider_calls") or 0) + int(ev.get("llm_calls") or 0)
            cost = (
                f"{calls} model call(s), {ev.get('model_latency_ms', 0):.0f} ms, {ev.get('tokens', 0)} tokens"
                if calls
                else "0 model calls (deterministic)"
            )
            events.append(
                {
                    "id": f"t{k}",
                    "date": ev["at"],
                    "title": f"Intake routed by {ev.get('engine')}: {ev.get('format')} → {ev.get('tool')}",
                    "detail": (
                        f"confidence {conf:.2f}"
                        if isinstance(conf, int | float)
                        else "no calibrated confidence"
                    )
                    + f" · {cost}"
                    + (f" · ambiguous: {', '.join(ev['ambiguous'])}" if ev.get("ambiguous") else "")
                    + (f" · fallback: {ev['fallback_reason']}" if ev.get("fallback_reason") else "")
                    + (
                        f" · kickback [{ev.get('kickback_code')}] drafted for the owner"
                        if ev.get("kickback")
                        else ""
                    )
                    + (" · owner review required" if ev.get("review_required") else "")
                    + (
                        " · decided before extraction; the tool decision chose the extractor"
                        if ev.get("before_extraction")
                        else ""
                    ),
                    "kind": "check",
                }
            )
        elif name == "document_extracted":
            k += 1
            events.append(
                {
                    "id": f"t{k}",
                    "date": ev["at"],
                    "title": f"Extracted {ev.get('filename')} with {ev.get('extractor')}",
                    "detail": f"tool decision {ev.get('tool')}"
                    + (f" · fallback: {ev['fallback']}" if ev.get("fallback") else " · as decided")
                    + (f" · {'; '.join(ev['warnings'])}" if ev.get("warnings") else ""),
                    "kind": "check",
                }
            )
        elif name in ("kickback_drafted", "kickback_approved", "kickback_declined", "kickback_sent"):
            k += 1
            label = {
                "kickback_drafted": "Kickback email drafted (awaiting the owner)",
                "kickback_approved": f"Kickback email approved by {ev.get('actor')}",
                "kickback_declined": f"Kickback email declined by {ev.get('actor')}",
                "kickback_sent": f"Kickback email sent by {ev.get('actor')} (Cedar P-09)",
            }[name]
            events.append(
                {
                    "id": f"t{k}",
                    "date": ev["at"],
                    "title": label,
                    "detail": f"to {ev.get('to')} · template {ev.get('code')}"
                    + (f" · via {ev['via']} ({ev.get('message_id')})" if ev.get("via") else "")
                    + (f" · {ev['note']}" if ev.get("note") else "")
                    + (f" · {ev['reason']}" if ev.get("reason") else ""),
                    "kind": "change" if name != "kickback_drafted" else "check",
                }
            )
        elif name == "sender_checked":
            k += 1
            flags = ev.get("flags") or []
            events.append(
                {
                    "id": f"t{k}",
                    "date": ev["at"],
                    "title": "Sender check" + (" passed" if not flags else f": {len(flags)} flag(s)"),
                    "detail": ", ".join(flags) if flags else "SPF/DKIM/DMARC pass",
                    "kind": "check",
                }
            )
        elif name == "vendor_resolved":
            k += 1
            events.append(
                {
                    "id": f"t{k}",
                    "date": ev["at"],
                    "title": f"Vendor resolution: {ev.get('status')}",
                    "detail": ", ".join(ev.get("matched_on") or []) or None,
                    "kind": "check",
                }
            )
        elif name == "kernel_checked":
            k += 1
            flags = ev.get("flags") or []
            events.append(
                {
                    "id": f"t{k}",
                    "date": ev["at"],
                    "title": "Deterministic checks" + (" clean" if not flags else f": {len(flags)} flag(s)"),
                    "detail": "; ".join(flags) if flags else None,
                    "kind": "check",
                }
            )
        elif name == "scored":
            k += 1
            events.append(
                {
                    "id": f"t{k}",
                    "date": ev["at"],
                    "title": f"Risk model scored ({ev.get('scorer')})",
                    "detail": f"legitimacy {round(float(ev.get('legitimacy') or 0) * 100)}% · top class {ev.get('top_class')}",
                    "kind": "check",
                }
            )
        elif name == "policy":
            k += 1
            events.append(
                {
                    "id": f"t{k}",
                    "date": ev["at"],
                    "title": f"Policy lane: {str(ev.get('lane')).replace('_', ' ')}",
                    "detail": "; ".join(ev.get("reasons") or []) or None,
                    "kind": "check",
                }
            )
        elif name == "resolution":
            k += 1
            events.append(
                {
                    "id": f"t{k}",
                    "date": ev["at"],
                    "title": f"Owner action: {str(ev.get('kind')).replace('_', ' ')}",
                    "detail": ev.get("note") or None,
                    "kind": "note",
                }
            )
        elif name == "paid":
            k += 1
            events.append(
                {
                    "id": f"t{k}",
                    "date": ev["at"],
                    "title": "Settled",
                    "detail": f"tx {ev.get('tx_id')}",
                    "kind": "payment",
                }
            )
    return events


def checklist_of(card: PaymentCard) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    done_kinds = {r.kind for r in card.resolutions}
    p = card.policy
    if p:
        for i, action in enumerate(p.required_actions, start=1):
            done = (
                (p.lane != Lane.HOLD)
                or ("confirm" in action and "confirm_bank" in done_kinds)
                or ("override" in action and "limit_override" in done_kinds)
            )
            items.append({"id": f"c{i}", "text": action[0].upper() + action[1:], "done": bool(done)})
    if card.investigation:
        for j, q in enumerate(card.investigation.vendor_questions[:3], start=1):
            items.append(
                {
                    "id": f"q{j}",
                    "text": q,
                    "done": "confirm_bank" in done_kinds or "resolve_risk" in done_kinds,
                }
            )
    if card.vendor and card.policy and card.policy.lane == Lane.HOLD:
        items.append(
            {
                "id": "c-phone",
                "text": f"Call the vendor on the number already on file: {card.vendor.phone}",
                "done": "confirm_bank" in done_kinds,
            }
        )
    return items


def audit_notes_of(card: PaymentCard) -> list[dict[str, Any]]:
    labels = {
        "approve": "Approved",
        "owner_hold": "Held",
        "release_hold": "Hold released",
        "appeal": "Appeal",
        "resolve_risk": "Risk resolved",
        "confirm_bank": "Bank change confirmed",
        "limit_override": "Limit override",
    }
    notes = []
    for i, r in enumerate(reversed(card.resolutions), start=1):
        text = f"{labels.get(r.kind, r.kind)}: {r.note}" if r.note else labels.get(r.kind, r.kind)
        if r.method:
            text += f" ({r.method})"
        notes.append({"id": f"n{i}", "at": r.at, "text": text, "author": r.actor})
    return notes


def _relations(card: PaymentCard, run: Run) -> tuple[str | None, str | None, str | None]:
    """(duplicate_of card id, split_with card id, duplicate note). Only real card ids become links;
    a duplicate of an already-paid invoice is described in the note instead."""
    ch = card.checks
    dup = ch.get("duplicate_of")
    duplicate_of = None
    if dup:
        m = re.search(r"invoice (\S+) in this batch", str(dup))
        if m:
            for other in run.card_list():
                if other.id != card.id and other.invoice.invoice_number == m.group(1):
                    duplicate_of = other.id
                    break
    split_with = None
    group = ch.get("split_group") or []
    others = [cid for cid in group if cid != card.id]
    if others:
        split_with = others[0]
    return duplicate_of, split_with, (str(dup) if dup else None)


def _source(card: PaymentCard) -> str:
    src = card.invoice.source
    if src == "email":
        return "email"
    if src in ("upload", "pdf_text"):
        return "upload"
    return "json"


def _received_at(run: Run, card: PaymentCard) -> str:
    try:
        idx = int(card.id.rsplit(".", 1)[1]) - 1
        sub = run.submissions[idx]
        if sub.received_at:
            return sub.received_at
    except (ValueError, IndexError):
        pass
    return run.created_at


def payment_view(engine: VouchEngine, run: Run, card: PaymentCard) -> dict[str, Any]:
    inv = card.invoice
    vendor = engine.vendors.get(inv.vendor_id or "") or card.vendor
    duplicate_of, split_with, duplicate_note = _relations(card, run)
    ring = (
        ring_graph(engine.graph, engine.vendors, inv.vendor_id)
        if card.checks.get("shared_attributes")
        else None
    )
    receipt = dict(card.receipt) if card.receipt else None
    if receipt and not receipt.get("explorer_url"):
        receipt["explorer_url"] = (
            f"{engine.settings.public_url.rstrip('/')}/v1/receipts/{receipt.get('tx_id')}"
        )
    return {
        "id": card.id,
        "run_id": run.id,
        "vendor": vendor_view(vendor, card, engine.today),
        "invoice_number": inv.invoice_number,
        "amount": inv.amount_cents / 100,
        "amount_cents": inv.amount_cents,
        "payable_cents": card.payable_cents,
        "currency": inv.currency,
        "issue_date": inv.issue_date.isoformat(),
        "due_date": inv.due_date.isoformat(),
        "status": vouch_status(card),
        "lifecycle": lifecycle_of(card),
        "risk": risk_of(card),
        "trust_score": trust_score(card),
        "reason": card.explanation or engine.template_explanation(card),
        "explanation_source": card.explanation_source,
        "fast_pay_eligible": bool(card.policy and card.policy.lane == Lane.FAST_PAY),
        "source": _source(card),
        "received_at": _received_at(run, card),
        "duplicate_of": duplicate_of,
        "split_with": split_with,
        "duplicate_note": duplicate_note,
        "evidence": evidence_of(card),
        "timeline": timeline_of(card, engine.today),
        "checklist": checklist_of(card),
        "ring": ring.model_dump(by_alias=True) if ring else None,
        "audit_notes": audit_notes_of(card),
        # engine facts (the detail panel and the judges' API view)
        "lane": card.policy.lane.value if card.policy else None,
        "card_status": card.status.value,
        "policy_reasons": card.policy.reasons if card.policy else [],
        "required_actions": card.policy.required_actions if card.policy else [],
        "legitimacy": card.scores.legitimacy if card.scores else None,
        "risk_scores": card.scores.risk if card.scores else None,
        "anomaly": card.scores.anomaly if card.scores else None,
        "lime": card.scores.lime if card.scores else [],
        "lime_class": card.scores.lime_class if card.scores else None,
        "scorer": card.scores.scorer if card.scores else None,
        "model_version": card.scores.model_version if card.scores else None,
        "vendor_match": card.resolution.model_dump() if card.resolution else None,
        "sender": card.sender.model_dump() if card.sender else None,
        # which engine routed the document (decider / hackathon-chat / deterministic) and why; advisory only.
        # intake.decisions is the decision chain (question, options, answer, engine, latency, tokens).
        "intake": card.intake.model_dump() if card.intake else None,
        # the drafted reply to the sender, if any; status awaiting_owner | approved | declined, never auto-sent
        "kickback": card.intake.kickback_draft.model_dump()
        if card.intake and card.intake.kickback_draft
        else None,
        "funding": card.funding,
        "investigation": card.investigation.model_dump() if card.investigation else None,
        "flags": card.flags,
        "amount_origin": inv.amount_origin,
        "receipt": receipt,
        "settlement_tx_id": receipt.get("tx_id") if receipt else None,
        "explorer_url": receipt.get("explorer_url") if receipt else None,
    }


def receipt_view(
    *,
    batch_id: str,
    settlements: list[dict[str, Any]],
    cards: list[tuple[Run, PaymentCard]],
    funding: str,
    scheduled_for: str | None,
    adapter_name: str,
    network: str,
    public_url: str = "",
) -> dict[str, Any]:
    payments = [p for s in settlements for p in s.get("payments", [])]
    by_card = {p["card_id"]: p for p in payments}
    first = payments[0] if payments else {}

    def link(rec: dict[str, Any]) -> str:
        url = rec.get("batch_explorer_url") or rec.get("explorer_url")
        if url:
            return str(url)
        tx = rec.get("tx_id")
        return f"{public_url.rstrip('/')}/v1/receipts/{tx}" if tx and public_url else ""

    tx_id = first.get("batch_tx_id") or first.get("tx_id") or ""
    explorer = link(first) if first else ""
    lines = []
    for run, card in cards:
        rec = by_card.get(card.id, card.receipt or {})
        lines.append(
            {
                "payment_id": card.id,
                "run_id": run.id,
                "vendor_name": card.invoice.vendor_name,
                "invoice_number": card.invoice.invoice_number,
                "amount": card.payable_cents / 100,
                "amount_cents": card.payable_cents,
                "tx_id": rec.get("tx_id"),
                "explorer_url": link(rec) if rec else None,
                "status": rec.get("status") or card.status.value,
            }
        )
    total = sum(c.payable_cents for _, c in cards)
    simulated = adapter_name == "mock"
    if adapter_name == "xrpl":
        if "USD" in network or "IOU" in network.upper():
            network_label = f"XRPL Testnet · {network.split('-')[-1].upper()} IOU"
        elif "xrp" in network.lower():
            network_label = "XRPL Testnet · XRP"
        else:
            network_label = "XRPL Testnet"
    else:
        network_label = f"{network} (simulated)"
    return {
        "batch_id": batch_id,
        "tx_id": tx_id,
        "explorer_url": explorer,
        "settled_at": iso(utcnow()),
        "funding": funding,
        "scheduled_for": scheduled_for,
        "total_amount": total / 100,
        "total_cents": total,
        "lines": lines,
        "network": network_label,
        "adapter": adapter_name,
        "simulated": simulated,
        "fee_usd": 0,
        "transactions": [
            {
                "tx_id": p.get("tx_id"),
                "explorer_url": link(p),
                "batch_tx_id": p.get("batch_tx_id"),
                "batch_explorer_url": p.get("batch_explorer_url"),
                "status": p.get("status"),
                "card_id": p.get("card_id"),
            }
            for p in payments
        ],
    }
