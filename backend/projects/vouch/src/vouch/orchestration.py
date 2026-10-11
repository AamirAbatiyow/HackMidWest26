"""Orchestrator timeline: the ordered steps one payment card went through, with the tool or model that
actually ran each step, its measured duration, a status and a one-line result.

Built only from recorded facts: the card's own event log (``PaymentCard.timeline``), the run's node events
(``Run.events``: ``node_start`` / ``node_done`` carry the measured ms, LLM calls and tokens per graph node),
the intake decision chain (``IntakeClassification``: which engine decided, how many model calls) and the
kernel/scorer/policy outcomes on the card. Nothing here infers a tool that was not recorded: an intake
routed by code reports ``deterministic route``; the Decider is named only when ``engine == "decider"``.

Node durations are measured per graph node, i.e. once for the whole batch, so a step's ``duration_ms``
has ``duration_scope == "node"`` (shared by every card in the run) unless the step has its own measured
latency (``"step"``: Decider / chat classifier calls, owner approval wait).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from vouch.cards import PaymentCard
from vouch.domain import CardStatus, Lane
from vouch.engine import Run, VouchEngine
from vouch.kernel import format_cents, normalize_account

STATUS_OK = "ok"
STATUS_FLAG = "flag"
STATUS_HOLD = "hold"
STATUS_PENDING = "pending"
NODE_TIMED = object()  # ``duration_ms`` sentinel: use the measured ms of the graph node that ran the step

# Graph nodes in pipeline order -> the steps they produce (for pending placeholders while a run is live).
NODE_STEPS: list[tuple[str, list[str]]] = [
    ("intake", ["intake", "format decision", "read/parse"]),
    ("resolve", ["vendor screen"]),
    ("sender", ["sender check"]),
    ("kernel", ["bank check", "duplicate check", "ring check", "amount check"]),
    ("score", ["score"]),
    ("investigate", ["investigate"]),
    ("policy", ["policy"]),
    ("funding", ["funding"]),
    ("explain", ["explain"]),
    ("fast_pay", ["settlement"]),
    ("settle", ["owner approval", "settlement"]),
]

ENGINE_LABELS = {
    "deterministic": "deterministic route",
    "decider": "Strands Decider 2B",
    "hackathon-chat": "hackathon-chat (Llama 3.3 70B)",
}
EXTRACTOR_LABELS = {
    "pypdf+pdfplumber": "PDF text parser (pypdf + pdfplumber)",
    "pypdf+pdfplumber+ocr": "PDF parser + OCR fallback",
    "ocr:tesseract": "OCR (Tesseract)",
    "ocr:rapidocr": "OCR (RapidOCR)",
    "ocr:none": "OCR unavailable",
    "openpyxl": "Excel parser (openpyxl)",
    "csv": "CSV parser",
    "email-body": "email-body parser",
    "text": "plain-text parser",
}
TOOL_LABELS = {
    "pdf_text": "PDF text parser",
    "image_ocr": "OCR",
    "excel_reader": "Excel parser",
    "csv_reader": "CSV parser",
    "body_parser": "email-body parser",
    "request_resubmission": "request resubmission",
}
SCORER_LABELS = {
    "inference-service": "VouchNet scorer (inference service) + LIME",
    "local-torch": "VouchNet scorer (local torch) + LIME",
    "heuristic-fallback": "heuristic scorer (VouchNet unavailable)",
}
ADAPTER_LABELS = {"xrpl": "XRPL testnet settlement", "mock": "mock ledger (simulated)", "arc": "Arc testnet"}
CEDAR_LABELS = {"cedar": "Cedar (cedarpy)", "python-mirror": "Cedar rules (python mirror)"}


def _ms(value: Any) -> int | None:
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return None


def _ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _diff_ms(a: Any, b: Any) -> int | None:
    ta, tb = _ts(a), _ts(b)
    if ta is None or tb is None:
        return None
    return max(0, int((tb - ta).total_seconds() * 1000))


def _node_runs(run: Run) -> dict[str, list[dict[str, Any]]]:
    """Every ``node_done`` event per node, in order (the first is the main pipeline, later ones re-runs)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for ev in run.events:
        if ev.get("type") == "node_done" and ev.get("node"):
            out.setdefault(str(ev["node"]), []).append(ev)
    return out


class _Steps:
    def __init__(self, run: Run) -> None:
        self.items: list[dict[str, Any]] = []
        self.nodes = _node_runs(run)

    def node_timing(self, node: str, occurrence: int = 0) -> tuple[int | None, dict[str, Any]]:
        evs = self.nodes.get(node) or []
        if occurrence < len(evs):
            ev = evs[occurrence]
            return _ms(ev.get("ms")), {
                "llm_calls": int(ev.get("llm_calls") or 0),
                "tokens": int(ev.get("tokens") or 0),
            }
        return None, {}

    def add(
        self,
        step: str,
        *,
        node: str,
        tool: str,
        result: str,
        status: str = STATUS_OK,
        engine: str | None = None,
        at: Any = None,
        duration_ms: Any = NODE_TIMED,
        duration_scope: str | None = None,
        detail: dict[str, Any] | None = None,
        node_occurrence: int | None = None,
    ) -> dict[str, Any]:
        node_ms, usage = (None, {})
        if duration_ms is NODE_TIMED:
            node_ms, usage = self.node_timing(node, node_occurrence or 0)
            duration_ms = node_ms
        item = {
            "order": len(self.items) + 1,
            "step": step,
            "node": node,
            "tool": tool,
            "engine": engine,
            "duration_ms": duration_ms,
            "duration_scope": duration_scope or ("node" if node_ms is not None else None),
            "status": status,
            "result": result,
            "at": at,
            "detail": {**usage, **(detail or {})},
        }
        self.items.append(item)
        return item


def _events(card: PaymentCard, *names: str) -> list[dict[str, Any]]:
    return [ev for ev in card.timeline if ev.get("event") in names]


def _first(card: PaymentCard, *names: str) -> dict[str, Any] | None:
    evs = _events(card, *names)
    return evs[0] if evs else None


def _money(cents: int | None, currency: str = "USD") -> str:
    return format_cents(int(cents or 0), currency)


def _submission(run: Run, card: PaymentCard) -> Any:
    try:
        idx = int(card.id.rsplit(".", 1)[1]) - 1
        return run.submissions[idx]
    except (ValueError, IndexError):
        return None


# ----------------------------------------------------------------------------------------- steps ----


def _intake_steps(engine: VouchEngine, run: Run, card: PaymentCard, steps: _Steps) -> None:
    inv = card.invoice
    sub = _submission(run, card)
    docs = list(getattr(sub, "documents", []) or [])
    attachments = [d for d in docs if d.get("kind") != "email_body"]
    source = inv.source or "json"
    channel = {
        "email": "email intake (.eml)",
        "upload": "file upload",
        "text": "text submission",
        "json": "JSON API (owner's system)",
        "pdf_text": "PDF text",
    }.get(source, source)
    created = next(
        (ev for ev in run.events if ev.get("type") == "card_created" and ev.get("card_id") == card.id), None
    )
    if attachments:
        names = ", ".join(str(d.get("filename") or d.get("kind") or "attachment") for d in attachments[:3])
        received = f"{len(attachments)} attachment(s): {names}"
    elif inv.raw_text:
        received = f"{len(inv.raw_text)} chars of invoice text"
    elif getattr(sub, "headers", None):
        received = "email headers + structured fields (no document)"
    else:
        received = "structured fields only (no document)"
    _, intake_usage = steps.node_timing("intake")
    steps.add(
        "intake",
        node="intake",
        tool=channel,
        engine="deterministic",
        result=f"received via {source} · {received}",
        at=created.get("at") if created else None,
        detail={
            "source": source,
            "submitted_by": inv.submitted_by,
            "documents": [
                {k: d.get(k) for k in ("filename", "kind", "extractor", "tool", "fallback") if k in d}
                for d in attachments
            ],
            "ignored_fields": (_first(card, "ignored_fields") or {}).get("fields", []),
        },
    )

    cls = card.intake
    classified = _first(card, "intake_classified")
    if cls is not None or classified is not None:
        eng = str((classified or {}).get("engine") or (cls.engine if cls else "deterministic"))
        fmt = str((classified or {}).get("format") or (cls.format if cls else "?"))
        tool = str((classified or {}).get("tool") or (cls.tool if cls else "?"))
        calls = int(cls.decider_calls + cls.llm_calls) if cls else 0
        model_ms = _ms(cls.model_latency_ms) if cls else None
        decisions = _events(card, "intake_decision")
        rejected = [d for d in decisions if not d.get("accepted")]
        review = bool(cls and cls.review_required) or bool((classified or {}).get("review_required"))
        kickback = bool(cls and cls.kickback) or bool((classified or {}).get("kickback"))
        if calls:
            how = f"{calls} model call(s), {model_ms or 0} ms"
        else:
            how = "0 model calls, the route was obvious to code"
        result = f"{ENGINE_LABELS.get(eng, eng)}: {fmt} → {TOOL_LABELS.get(tool, tool)} · {how}"
        if cls and cls.ambiguous:
            result += f" · ambiguous: {', '.join(cls.ambiguous)}"
        if rejected:
            result += f" · {len(rejected)} answer(s) rejected by schema validation"
        if kickback:
            result += f" · kickback drafted [{cls.kickback_code if cls else '?'}], awaits the owner"
        if review:
            result += " · owner review required"
        status = STATUS_HOLD if (kickback or review) else (STATUS_FLAG if rejected else STATUS_OK)
        steps.add(
            "format decision",
            node="intake",
            tool=ENGINE_LABELS.get(eng, eng),
            engine=eng,
            result=result,
            status=status,
            at=(classified or {}).get("at") or (cls.at if cls else None),
            duration_ms=model_ms if calls else NODE_TIMED,
            duration_scope="step" if calls else None,
            detail={
                "format": fmt,
                "tool": tool,
                "format_confidence": cls.format_confidence if cls else None,
                "deterministic_format": cls.deterministic_format if cls else None,
                "deterministic_tool": cls.deterministic_tool if cls else None,
                "agrees_with_deterministic": cls.agrees_with_deterministic if cls else None,
                "decider_calls": cls.decider_calls if cls else 0,
                "llm_calls": cls.llm_calls if cls else 0,
                "tokens": cls.tokens if cls else 0,
                "fallback_reason": cls.fallback_reason if cls else None,
                "before_extraction": cls.before_extraction if cls else False,
                "decisions": [
                    {
                        "key": d.get("key"),
                        "answer": d.get("answer"),
                        "engine": d.get("engine"),
                        "accepted": d.get("accepted"),
                        "latency_ms": _ms(d.get("latency_ms")),
                        "reason_code": d.get("reason_code"),
                    }
                    for d in decisions
                ],
            },
        )
    elif _first(card, "intake_classification_failed"):
        failed = _first(card, "intake_classification_failed") or {}
        steps.add(
            "format decision",
            node="intake",
            tool="deterministic route",
            engine="deterministic",
            result=f"routing failed, default extractor used · {failed.get('error')}",
            status=STATUS_FLAG,
            at=failed.get("at"),
        )

    # read / parse
    extracted = _events(card, "document_extracted")
    notes = [str(ev.get("note")) for ev in _events(card, "intake_note")]
    llm_intake = intake_usage.get("llm_calls", 0) > 0 and bool(inv.raw_text)
    if extracted:
        ex = extracted[0]
        extractor = str(ex.get("extractor") or "")
        tool = EXTRACTOR_LABELS.get(extractor, extractor or "default extractor")
        how = f"fallback: {ex['fallback']}" if ex.get("fallback") else "as routed"
    elif cls and cls.extractor_used:
        extractor = cls.extractor_used
        tool = EXTRACTOR_LABELS.get(extractor, extractor)
        how = "extractor recorded by intake"
    elif inv.raw_text:
        tool = "kernel text parser" + (" + Strands intake agent" if llm_intake else "")
        how = "regex field parser over the text" + (
            f"; intake agent ({engine.llm.model_name}) quoted fields, kernel verified them verbatim"
            if llm_intake
            else ""
        )
    else:
        tool = "structured fields (kernel)"
        how = "fields from the owner's system, parsed by the kernel"
    parts = [
        f"amount {_money(inv.amount_cents, inv.currency)}",
        f"invoice {inv.invoice_number}",
        f"vendor {inv.vendor_name}",
    ]
    acct = normalize_account(inv.bank_account) or ""
    if acct:
        parts.append(f"bank ····{acct[-4:]}")
    origin = inv.amount_origin
    status = STATUS_OK
    if origin == "llm":
        parts.append("amount came from the LLM, not the document")
        status = STATUS_FLAG
    elif origin == "missing":
        parts.append("no verifiable amount")
        status = STATUS_FLAG
    unread = [n for n in notes if n.startswith("could not read")]
    if unread:
        parts.append(unread[0])
        status = STATUS_FLAG
    warnings = [w for ev in extracted for w in (ev.get("warnings") or [])]
    steps.add(
        "read/parse",
        node="intake",
        tool=tool,
        engine=engine.llm.model_name if llm_intake else "deterministic",
        result=f"{tool}: " + " · ".join(parts),
        status=status,
        at=(extracted[0].get("at") if extracted else (created.get("at") if created else None)),
        detail={
            "how": how,
            "amount_origin": origin,
            "amount_cents": inv.amount_cents,
            "currency": inv.currency,
            "issue_date": inv.issue_date.isoformat(),
            "due_date": inv.due_date.isoformat(),
            "po_number": inv.po_number,
            "remit_email": inv.remit_email,
            "line_items": len(inv.line_items),
            "notes": notes,
            "warnings": warnings,
            "documents": [
                {k: ev.get(k) for k in ("filename", "kind", "extractor", "tool", "fallback")}
                for ev in extracted
            ],
        },
    )


def _vendor_steps(card: PaymentCard, steps: _Steps) -> None:
    res = card.resolution
    ev = _first(card, "vendor_resolved")
    if res is None and ev is None:
        return
    status_word = str((ev or {}).get("status") or (res.status if res else "?"))
    matched = list((ev or {}).get("matched_on") or (res.matched_on if res else []))
    conf = (ev or {}).get("confidence", res.confidence if res else None)
    tool = "vendor resolver (master file)" + (" + embedding index" if res and res.embedding_used else "")
    if status_word == "known":
        name = res.vendor_name if res else card.invoice.vendor_name
        result = f"known vendor {name} · matched on {', '.join(matched) or 'exact id'}"
        status = STATUS_OK
    elif status_word == "new":
        result = f"not on the master file · claim '{card.invoice.vendor_name}' has no match"
        status = STATUS_FLAG
    else:
        n = len(res.candidates) if res else 0
        result = f"ambiguous match · {n} candidate(s), fuzzy name only"
        status = STATUS_FLAG
    if isinstance(conf, int | float):
        result += f" · confidence {float(conf):.2f}"
    steps.add(
        "vendor screen",
        node="resolve",
        tool=tool,
        engine="deterministic",
        result=result,
        status=status,
        at=(ev or {}).get("at"),
        detail={
            "status": status_word,
            "matched_on": matched,
            "confidence": conf,
            "vendor_id": res.vendor_id if res else None,
            "candidates": [c.model_dump() for c in (res.candidates if res else [])][:5],
            "notes": [str(n.get("note")) for n in _events(card, "resolution_note")],
        },
    )


def _sender_step(card: PaymentCard, steps: _Steps) -> None:
    s = card.sender
    ev = _first(card, "sender_checked")
    if not s or not s.checked:
        return
    flags = list((ev or {}).get("flags") or s.flags)
    tool = "SPF/DKIM/DMARC + lookalike-domain check"
    if flags:
        result = f"{len(flags)} flag(s): {', '.join(f.replace('_', ' ') for f in flags[:3])}"
        status = STATUS_FLAG
    else:
        result = f"authentication passed for {s.from_domain}"
        status = STATUS_OK
    steps.add(
        "sender check",
        node="sender",
        tool=tool,
        engine="deterministic",
        result=result,
        status=status,
        at=(ev or {}).get("at"),
        detail={
            "from": s.from_addr,
            "reply_to": s.reply_to or None,
            "auth_pass": s.auth_pass,
            "flags": flags,
            "risk": s.risk,
            "lookalike": s.lookalike.model_dump() if s.lookalike else None,
        },
    )


def _kernel_steps(engine: VouchEngine, card: PaymentCard, steps: _Steps) -> None:
    ch = card.checks
    ev = _first(card, "kernel_checked", "credit_note")
    if not ch and ev is None:
        return
    at = (ev or {}).get("at")
    inv = card.invoice
    if inv.is_credit_note:
        steps.add(
            "amount check",
            node="kernel",
            tool="kernel (credit allocation)",
            engine="deterministic",
            result=f"credit note {_money(inv.amount_cents, inv.currency)} applied to open invoices",
            at=at,
        )
        return
    vendor = card.vendor
    # bank
    if vendor is None:
        bank_result, bank_status = "no master record to compare bank details against", STATUS_FLAG
    elif ch.get("bank_mismatch"):
        bank_result, bank_status = "invoice bank account differs from the master file", STATUS_FLAG
    elif ch.get("bank_change_recent") and not ch.get("bank_change_confirmed"):
        days = vendor.bank_changed_days_ago
        bank_result, bank_status = (
            f"master-file bank details changed {days} day(s) ago, no call-back on record",
            STATUS_FLAG,
        )
    elif ch.get("bank_change_recent"):
        bank_result, bank_status = "bank details changed recently, confirmed out-of-band", STATUS_OK
    else:
        acct = normalize_account(vendor.bank_account) or ""
        bank_result, bank_status = (
            "account matches the master file" + (f" (····{acct[-4:]})" if acct else ""),
            STATUS_OK,
        )
    if ch.get("remit_email_mismatch"):
        bank_result += " · remittance email domain differs from the vendor on file"
        bank_status = STATUS_FLAG
    steps.add(
        "bank check",
        node="kernel",
        tool="kernel: bank-details check",
        engine="deterministic",
        result=bank_result,
        status=bank_status,
        at=at,
        detail={
            k: ch.get(k)
            for k in (
                "bank_mismatch",
                "bank_change_recent",
                "bank_change_confirmed",
                "contact_change_recent",
                "remit_email_mismatch",
            )
        },
    )
    # duplicate / split
    dup, group = ch.get("duplicate_of"), list(ch.get("split_group") or [])
    if dup:
        dup_result, dup_status = f"possible duplicate of {dup}", STATUS_FLAG
    elif group:
        dup_result, dup_status = (
            f"split pattern: {len(group)} invoices just under the approval limit, together "
            f"{_money(ch.get('split_total_cents'), inv.currency)}",
            STATUS_FLAG,
        )
    else:
        dup_result, dup_status = "no duplicate · no split pattern", STATUS_OK
    steps.add(
        "duplicate check",
        node="kernel",
        tool="kernel: duplicate/split detector",
        engine="deterministic",
        result=dup_result,
        status=dup_status,
        at=at,
        detail={"duplicate_of": dup, "split_group": group, "split_total_cents": ch.get("split_total_cents")},
    )
    # ring
    shared = dict(ch.get("shared_attributes") or {})
    if shared:
        bits = []
        for kind, others in shared.items():
            bits.append(f"{kind.replace('_', ' ')} shared with {len(others)} other vendor(s)")
        ring_result, ring_status = "ring check: " + "; ".join(bits), STATUS_FLAG
    elif vendor is None:
        ring_result, ring_status = "no master record, no graph edges to inspect", STATUS_OK
    else:
        ring_result, ring_status = "no shared bank account, tax id, phone or address", STATUS_OK
    linked = {
        kind: [engine.vendors[o].name if o in engine.vendors else o for o in others]
        for kind, others in shared.items()
    }
    steps.add(
        "ring check",
        node="kernel",
        tool="vendor graph (shared attributes)",
        engine="deterministic",
        result=ring_result,
        status=ring_status,
        at=at,
        detail={"shared_attributes": linked, "ring_score": card.scores.ring_score if card.scores else None},
    )
    # amount & limits
    bits = [f"{_money(card.payable_cents, inv.currency)} payable"]
    status = STATUS_OK
    limits = engine.limits
    if ch.get("over_single_limit"):
        bits.append(f"exceeds the single-payment limit {_money(limits.single_payment_limit_cents)}")
        status = STATUS_FLAG
    elif ch.get("over_approval_limit"):
        bits.append(f"over the approval limit {_money(limits.approval_limit_cents)} (owner approval)")
    elif ch.get("near_approval_limit"):
        bits.append(f"just under the approval limit {_money(limits.approval_limit_cents)}")
    else:
        bits.append(f"under the approval limit {_money(limits.approval_limit_cents)}")
    if not ch.get("line_items_match", True):
        bits.append("line items do not add up")
        status = STATUS_FLAG
    if not ch.get("amount_origin_ok", True):
        bits.append("amount not produced by the kernel")
        status = STATUS_FLAG
    if ch.get("injection"):
        bits.append("instructions aimed at the payment system found in the text")
        status = STATUS_FLAG
    if ch.get("no_po") and ch.get("no_delivery"):
        bits.append("no PO and no delivery confirmation")
        status = STATUS_FLAG if status == STATUS_OK and not ch.get("vendor_found") else status
    elif ch.get("no_po"):
        bits.append("no PO")
    ratio = ch.get("amount_ratio_milli") or 0
    if ratio and ch.get("history_count"):
        bits.append(f"{ratio / 1000:.1f}× the vendor's median invoice")
    if _first(card, "netted"):
        bits.append(f"credit applied: {_money((_first(card, 'netted') or {}).get('credit_applied_cents'))}")
    steps.add(
        "amount check",
        node="kernel",
        tool="kernel: amount & limits (integer cents)",
        engine="deterministic",
        result=" · ".join(bits),
        status=status,
        at=at,
        detail={
            k: ch.get(k)
            for k in (
                "over_approval_limit",
                "over_single_limit",
                "near_approval_limit",
                "line_items_match",
                "amount_origin_ok",
                "no_po",
                "no_delivery",
                "history_count",
                "history_median_cents",
                "amount_ratio_milli",
                "creep_milli",
                "urgency_terms",
                "injection",
            )
        }
        | {"flags": list(card.flags)},
    )


def _score_step(card: PaymentCard, steps: _Steps) -> None:
    s = card.scores
    ev = _first(card, "scored")
    if s is None and ev is None:
        return
    scorer = str((ev or {}).get("scorer") or (s.scorer if s else "?"))
    legit = float(
        (ev or {}).get("legitimacy")
        if ev and ev.get("legitimacy") is not None
        else (s.legitimacy if s else 0)
    )
    top = str((ev or {}).get("top_class") or (s.top_class if s else "?"))
    tool = SCORER_LABELS.get(scorer, scorer)
    result = f"legitimacy {round(legit * 100)}% · top class {top.replace('_', ' ')}"
    if s and s.lime:
        first = s.lime[0]
        result += f" · top factor: {first.get('label') or first.get('feature')}"
    status = STATUS_FLAG if (top != "honest" or legit < 0.6) else STATUS_OK
    steps.add(
        "score",
        node="score",
        tool=tool,
        engine=scorer,
        result=result,
        status=status,
        at=(ev or {}).get("at"),
        detail={
            "model_version": s.model_version if s else None,
            "legitimacy": s.legitimacy if s else None,
            "risk": s.risk if s else None,
            "anomaly": s.anomaly if s else None,
            "lime": (s.lime[:5] if s else []),
            "lime_class": s.lime_class if s else None,
            "features": len(card.features),
        },
    )


def _investigate_step(engine: VouchEngine, card: PaymentCard, steps: _Steps) -> None:
    inv = card.investigation
    ev = _first(card, "investigated")
    if inv is None and ev is None:
        return
    cls = str((ev or {}).get("investigator") or (inv.investigator if inv else "?"))
    source = str((ev or {}).get("source") or (inv.source if inv else "template"))
    rejected = [e for e in _events(card, "provenance_rejected") if e.get("role") == "investigator"]
    if source == "llm":
        tool = f"Strands investigator agent [{cls}] · {engine.llm.model_name}"
        eng = engine.llm.model_name
    else:
        tool = f"template investigator [{cls}] (no model call)"
        eng = "deterministic"
    result = (inv.summary if inv else "").strip() or f"{cls.replace('_', ' ')} investigation"
    if rejected:
        result += " · LLM report rejected by provenance check, template used"
    steps.add(
        "investigate",
        node="investigate",
        tool=tool,
        engine=eng,
        result=result[:200],
        status=STATUS_FLAG,
        at=(ev or {}).get("at"),
        detail={
            "investigator": cls,
            "source": source,
            "recommended_action": inv.recommended_action if inv else None,
            "evidence": inv.evidence if inv else [],
            "vendor_questions": inv.vendor_questions if inv else [],
            "provenance_ok": inv.provenance_ok if inv else None,
        },
    )


def _policy_result(lane: str, reasons: list[str]) -> tuple[str, str]:
    lane_label = lane.replace("_", " ")
    if lane == Lane.HOLD.value:
        return f"lane: hold · {'; '.join(reasons[:2]) or 'owner review'}", STATUS_HOLD
    if lane == Lane.FAST_PAY.value:
        return "lane: fast pay · verified small vendor under the standing limit, pays today", STATUS_OK
    return f"lane: {lane_label} · passes release policy, waits for the owner's batch approval", STATUS_OK


def _policy_step(
    card: PaymentCard, steps: _Steps, ev: dict[str, Any] | None, *, recheck: bool = False
) -> None:
    p = card.policy
    if ev is None and p is None:
        return
    lane = str((ev or {}).get("lane") or (p.lane.value if p else "standard"))
    reasons = list((ev or {}).get("reasons") or (p.reasons if p else []))
    result, status = _policy_result(lane, reasons)
    steps.add(
        "policy re-check" if recheck else "policy",
        node="policy",
        tool="release policy (Cedar-style, default deny)",
        engine="deterministic",
        result=result,
        status=status,
        at=(ev or {}).get("at"),
        duration_ms=None if recheck else NODE_TIMED,
        detail={
            "lane": lane,
            "reasons": reasons,
            "required_actions": p.required_actions if p else [],
            "actions_evaluated": ["payment:release", "payment:fast_pay"],
        },
    )


def _funding_step(card: PaymentCard, steps: _Steps) -> None:
    f = card.funding
    if not f:
        return
    action = str(f.get("action") or "")
    when = f.get("pay_on")
    result = {"pay_now": "pay now", "schedule": f"schedule for {when}"}.get(
        action, action or "no recommendation"
    )
    if f.get("reason"):
        result += f" · {f['reason']}"
    steps.add(
        "funding",
        node="funding",
        tool="cash-forecast recommender",
        engine="deterministic",
        result=result,
        detail=dict(f),
    )


def _explain_step(engine: VouchEngine, card: PaymentCard, steps: _Steps) -> None:
    if card.explanation_source == "pending":
        return
    rejected = [e for e in _events(card, "provenance_rejected") if e.get("role") == "explainer"]
    if card.explanation_source == "llm":
        tool = f"Strands explainer agent · {engine.llm.model_name}"
        eng = engine.llm.model_name
    else:
        tool = "template explanation (no model call)"
        eng = "deterministic"
    text = card.explanation.strip()
    result = text if len(text) <= 160 else text[:157] + "…"
    status = STATUS_OK
    if rejected:
        r = rejected[-1]
        unknown = r.get("unknown") or []
        result = (
            "LLM text rejected by the provenance check ("
            + (
                f"unknown amounts/dates: {', '.join(map(str, unknown[:3]))}"
                if unknown
                else "claims money moved"
            )
            + ") · template used"
        )
        status = STATUS_FLAG
    steps.add(
        "explain",
        node="explain",
        tool=tool,
        engine=eng,
        result=result,
        status=status,
        detail={
            "source": card.explanation_source,
            "provenance_rejections": len(rejected),
            "facts": len(card.facts),
        },
    )


def _authz_text(ev: dict[str, Any]) -> str:
    who = str(ev.get("principal") or "?")
    action = str(ev.get("action") or "?")
    eng = str(ev.get("engine") or "cedar")
    rules = list(ev.get("rules") or [])
    verdict = "allowed" if ev.get("allowed") else "denied"
    return f"{CEDAR_LABELS.get(eng, eng)}: {action} {verdict} for {who}" + (
        f" · {', '.join(rules[:2])}" if rules else ""
    )


def _post_run_steps(engine: VouchEngine, run: Run, card: PaymentCard, steps: _Steps) -> None:
    """Owner actions, Cedar authorizations, policy re-checks and settlement, in the order they happened."""
    p = card.policy
    awaiting = next((e for e in run.events if e.get("type") == "awaiting_approval"), None)
    decision = next((e for e in run.events if e.get("type") == "owner_decision"), None)
    later = [
        ev
        for ev in card.timeline
        if ev.get("event")
        in (
            "resolution",
            "owner_approved",
            "authorized",
            "paid",
            "settlement_failed",
            "settle_blocked_by_policy",
            "batch_blocked",
            "scheduled",
            "kickback_approved",
            "kickback_declined",
            "kickback_sent",
            "appeal_queued",
        )
    ]
    policy_evs = _events(card, "policy")[1:]
    if card.status == CardStatus.CREDIT:
        return
    has_card_approval = any(
        e["event"] == "owner_approved" or (e["event"] == "resolution" and e.get("kind") == "approve")
        for e in later
    )
    if (
        not has_card_approval
        and decision
        and decision.get("approved")
        and card.status
        in (
            CardStatus.PAID,
            CardStatus.APPROVED,
        )
    ):
        # Batch approval answered at the Strands interrupt (POST /v1/runs/{id}/approve): the card has no
        # event of its own, the run does.
        later.append({"event": "owner_decision", "at": decision.get("at")})
    elif not has_card_approval and p and p.lane == Lane.FAST_PAY and card.status == CardStatus.PAID:
        steps.add(
            "owner approval",
            node="fast_pay",
            tool="standing rule (no interrupt)",
            engine="deterministic",
            result="not required · fast-pay standing rule for verified small vendors",
            status=STATUS_OK,
            duration_ms=None,
            detail={"lane": p.lane.value, "reasons": p.reasons},
        )
    elif not has_card_approval and p and p.lane == Lane.HOLD and card.status == CardStatus.HOLD:
        steps.add(
            "owner approval",
            node="settle",
            tool="owner (human in the loop)",
            engine="owner",
            result="on hold, not denied · "
            + (p.required_actions[0] if p.required_actions else "owner review"),
            status=STATUS_HOLD,
            at=awaiting.get("at") if awaiting else None,
            duration_ms=None,
            detail={"required_actions": p.required_actions, "reasons": p.reasons},
        )
    elif not has_card_approval and run.status == "awaiting_approval" and card.status == CardStatus.READY:
        steps.add(
            "owner approval",
            node="settle",
            tool="owner (human in the loop)",
            engine="owner",
            result="waiting at the Strands interrupt for the owner's batch approval",
            status=STATUS_PENDING,
            at=awaiting.get("at") if awaiting else None,
            duration_ms=None,
            detail={"interrupt": awaiting.get("interrupt_id") if awaiting else None},
        )
    elif (
        not has_card_approval
        and decision
        and not decision.get("approved")
        and card.status == CardStatus.READY
    ):
        steps.add(
            "owner approval",
            node="settle",
            tool="owner (human in the loop)",
            engine="owner",
            result="owner declined the batch · nothing paid",
            status=STATUS_HOLD,
            at=decision.get("at"),
            duration_ms=None,
        )
    # Everything else the owner and the ledger did, chronologically.
    recheck_i = 0
    approval_seen = False
    for ev in sorted(later, key=lambda e: str(e.get("at") or "")):
        name = ev["event"]
        if name in ("owner_approved", "owner_decision") or (
            name == "resolution" and ev.get("kind") == "approve"
        ):
            if approval_seen:
                continue
            approval_seen = True
            wait = _diff_ms(awaiting.get("at"), ev.get("at")) if awaiting else None
            if name == "owner_decision":
                result = "batch approved at the Strands interrupt"
            else:
                result = f"approved by {ev.get('actor') or 'owner'}" + (
                    f" · {ev['note']}" if ev.get("note") else ""
                )
            steps.add(
                "owner approval",
                node="settle",
                tool="owner (human in the loop)",
                engine="owner",
                result=result,
                status=STATUS_OK,
                at=ev.get("at"),
                duration_ms=wait,
                duration_scope="step" if wait is not None else None,
                detail={
                    "interrupt": awaiting.get("interrupt_id") if awaiting else None,
                    "actor": ev.get("actor"),
                },
            )
        elif name == "resolution":
            kind = str(ev.get("kind") or "").replace("_", " ")
            steps.add(
                f"owner action: {kind}",
                node="policy",
                tool="owner (console)",
                engine="owner",
                result=(ev.get("note") or kind) or kind,
                status=STATUS_OK,
                at=ev.get("at"),
                duration_ms=None,
                detail={"actor": ev.get("actor"), "kind": ev.get("kind")},
            )
            if recheck_i < len(policy_evs):
                _policy_step(card, steps, policy_evs[recheck_i], recheck=True)
                recheck_i += 1
        elif name == "authorized":
            steps.add(
                "authorization",
                node="settle" if ev.get("action") == "settle" else "policy",
                tool=CEDAR_LABELS.get(str(ev.get("engine")), str(ev.get("engine"))),
                engine=str(ev.get("engine")),
                result=_authz_text(ev),
                status=STATUS_OK if ev.get("allowed") else STATUS_FLAG,
                at=ev.get("at"),
                duration_ms=None,
                detail={k: ev.get(k) for k in ("principal", "action", "allowed", "rules")},
            )
        elif name == "paid":
            adapter = engine.adapter
            rec = card.receipt or {}
            tx = str(ev.get("tx_id") or rec.get("tx_id") or "")
            steps.add(
                "settlement",
                node="fast_pay" if ev.get("lane") == "fast_pay" else "settle",
                tool=ADAPTER_LABELS.get(adapter.name, adapter.name),
                engine=adapter.name,
                result=f"settled {_money(card.payable_cents, card.invoice.currency)} via {str(ev.get('lane') or '').replace('_', ' ')} lane"
                + (f" · tx {tx[:10]}…" if tx else ""),
                status=STATUS_OK,
                at=ev.get("at"),
                detail={
                    "tx_id": tx or None,
                    "network": rec.get("network") or adapter.network,
                    "explorer_url": rec.get("explorer_url"),
                    "batch_tx_id": rec.get("batch_tx_id"),
                    "lane": ev.get("lane"),
                },
            )
        elif name == "settlement_failed":
            adapter = engine.adapter
            steps.add(
                "settlement",
                node="settle",
                tool=ADAPTER_LABELS.get(adapter.name, adapter.name),
                engine=adapter.name,
                result=f"settlement failed · {ev.get('error') or 'ledger rejected the payment'}",
                status=STATUS_FLAG,
                at=ev.get("at"),
                detail={"error": ev.get("error"), "tx_id": ev.get("tx_id")},
            )
        elif name in ("settle_blocked_by_policy", "batch_blocked"):
            reasons = list(ev.get("reasons") or [])
            steps.add(
                "settlement",
                node="settle",
                tool="release policy re-check at settlement",
                engine="deterministic",
                result="blocked before money moved · "
                + ("; ".join(reasons[:2]) or "policy forbade settlement"),
                status=STATUS_HOLD,
                at=ev.get("at"),
                duration_ms=None,
                detail={"reasons": reasons},
            )
        elif name == "scheduled":
            steps.add(
                "settlement",
                node="settle",
                tool="scheduled batch",
                engine="owner",
                result=f"scheduled for {ev.get('pay_on')} · batch {ev.get('batch_id')}",
                status=STATUS_PENDING,
                at=ev.get("at"),
                duration_ms=None,
                detail={"pay_on": ev.get("pay_on"), "batch_id": ev.get("batch_id")},
            )
        elif name.startswith("kickback_"):
            steps.add(
                "kickback email",
                node="policy",
                tool="owner (console) · Cedar P-08/P-09"
                if name != "kickback_sent"
                else f"mailer ({ev.get('via')})",
                engine="owner",
                result=name.replace("kickback_", "kickback ")
                + (f" by {ev['actor']}" if ev.get("actor") else ""),
                status=STATUS_OK,
                at=ev.get("at"),
                duration_ms=None,
                detail={k: ev.get(k) for k in ("to", "code", "via", "message_id", "note", "reason")},
            )
        elif name == "appeal_queued":
            steps.add(
                "vendor appeal",
                node="policy",
                tool="owner review queue",
                engine="owner",
                result=str(ev.get("note") or "appeal recorded"),
                status=STATUS_OK,
                at=ev.get("at"),
                duration_ms=None,
            )


def _pending_steps(run: Run, steps: _Steps) -> None:
    """While the graph is still running, show the nodes that have not finished yet as pending."""
    if run.status != "running":
        return
    done = set(steps.nodes)
    started = {str(e.get("node")) for e in run.events if e.get("type") == "node_start"}
    for node, names in NODE_STEPS:
        if node in done or node in ("fast_pay", "settle"):
            continue
        have = {s["step"] for s in steps.items}
        for name in names:
            if name in have:
                continue
            steps.add(
                name,
                node=node,
                tool="…",
                result="running" if node in started else "queued",
                status=STATUS_PENDING,
                duration_ms=None,
            )


# ------------------------------------------------------------------------------------------ api ----


def card_steps(engine: VouchEngine, run: Run, card: PaymentCard) -> list[dict[str, Any]]:
    steps = _Steps(run)
    _intake_steps(engine, run, card, steps)
    _vendor_steps(card, steps)
    _sender_step(card, steps)
    _kernel_steps(engine, card, steps)
    _score_step(card, steps)
    _investigate_step(engine, card, steps)
    _policy_step(card, steps, _first(card, "policy"))
    _funding_step(card, steps)
    _explain_step(engine, card, steps)
    _post_run_steps(engine, run, card, steps)
    _pending_steps(run, steps)
    return steps.items


def card_timeline(engine: VouchEngine, run: Run, card: PaymentCard) -> dict[str, Any]:
    steps = card_steps(engine, run, card)
    flagged = sum(s["status"] in (STATUS_FLAG, STATUS_HOLD) for s in steps)
    measured = [s["duration_ms"] for s in steps if s.get("duration_ms") is not None]
    return {
        "card_id": card.id,
        "payment_id": card.id,
        "run_id": run.id,
        "run_status": run.status,
        "invoice_number": card.invoice.invoice_number,
        "vendor": card.invoice.vendor_name,
        "amount_cents": card.invoice.amount_cents,
        "card_status": card.status.value,
        "lane": card.policy.lane.value if card.policy else None,
        "complete": run.status in ("completed", "awaiting_approval", "failed"),
        "last_seq": run.events[-1]["seq"] if run.events else 0,
        "steps": steps,
        "totals": {
            "steps": len(steps),
            "flagged": flagged,
            "measured_ms": sum(measured),
            "node_ms": {k: _ms(v) for k, v in run.node_ms.items()},
        },
    }


def run_timeline(engine: VouchEngine, run: Run) -> dict[str, Any]:
    nodes = [
        {
            "node": str(e.get("node")),
            "ms": _ms(e.get("ms")),
            "llm_calls": int(e.get("llm_calls") or 0),
            "tokens": int(e.get("tokens") or 0),
            "at": e.get("at"),
        }
        for e in run.events
        if e.get("type") == "node_done"
    ]
    return {
        "run_id": run.id,
        "label": run.label,
        "status": run.status,
        "created_at": run.created_at,
        "complete": run.status in ("completed", "awaiting_approval", "failed"),
        "last_seq": run.events[-1]["seq"] if run.events else 0,
        "nodes": nodes,
        "cards": [card_timeline(engine, run, c) for c in run.card_list()],
    }
