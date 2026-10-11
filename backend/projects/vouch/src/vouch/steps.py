"""Orchestrator timeline: the steps the payment graph actually ran for one card, in order.

Each step names the tool or model that did the work, whether it was deterministic code, an LLM call, a
model call or a human decision, how long it took on this card, its status and a one-line result. The
view is derived from what the engine already records (``PaymentCard.timeline``, ``PaymentCard.step_ms``,
``Run.node_ms``, the intake classification, scores, policy outcome, receipts); nothing is inferred that
the run did not record, and the classifier engine shown is the one the card carries (``deterministic``
unless the Decider or the chat classifier was actually asked and accepted).

Exposed as the additive ``steps`` key of the payment payload (``vouch.views.payment_view``).
"""

from __future__ import annotations

from typing import Any, Literal

from vouch.cards import PaymentCard
from vouch.domain import CardStatus, Lane
from vouch.engine import Run, VouchEngine
from vouch.kernel import format_cents

Kind = Literal["deterministic", "llm", "model", "human"]
Status = Literal["ok", "flagged", "hold", "denied", "pending", "skipped", "failed"]

# Graph node that owns each step (``Run.node_ms`` key) for the run-wide fallback duration.
NODE_OF = {
    "format": "intake",
    "read": "intake",
    "screen": "resolve",
    "check": "kernel",
    "score": "score",
    "investigate": "investigate",
    "policy": "policy",
    "writer": "explain",
    "settlement": "settle",
}

EXTRACTOR_LABELS = {
    "openpyxl": "Excel parser (openpyxl)",
    "pypdf+pdfplumber": "PDF text parser (pypdf + pdfplumber)",
    "pypdf+pdfplumber+ocr": "PDF OCR (pypdf + OCR)",
    "ocr:tesseract": "OCR (Tesseract)",
    "ocr:rapidocr": "OCR (RapidOCR)",
    "ocr:none": "OCR unavailable",
    "csv": "CSV reader",
    "email-body": "email body parser",
    "text": "plain-text parser",
}

SCORER_LABELS = {
    "local-torch": ("VouchNet (PyTorch, in-process)", "model"),
    "inference-service": ("VouchNet (PyTorch, inference service)", "model"),
    "heuristic-fallback": ("heuristic scorer (no model)", "deterministic"),
}

ENGINE_LABELS = {
    "decider": ("Strands Decider 2B", "model"),
    "hackathon-chat": ("hackathon-chat classifier (Strands structured output)", "llm"),
    "deterministic": ("deterministic route (MIME type / extension / magic bytes)", "deterministic"),
}


def _step(
    step_id: str,
    label: str,
    tool: str,
    kind: Kind,
    *,
    status: Status,
    summary: str,
    duration_ms: float | None,
    scope: str | None,
    at: str | None = None,
    detail: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": step_id,
        "label": label,
        "tool": tool,
        "kind": kind,
        "node": NODE_OF.get(step_id),
        "duration_ms": None if duration_ms is None else round(float(duration_ms), 1),
        # card: measured on this card · run: the graph node's time for the whole run · batch: one
        # settlement transaction shared by every card in it
        "duration_scope": None if duration_ms is None else scope,
        "status": status,
        "summary": summary,
        "detail": [d for d in (detail or []) if d],
        "at": at,
        **extra,
    }


def _event(card: PaymentCard, name: str) -> dict[str, Any] | None:
    for ev in card.timeline:
        if ev.get("event") == name:
            return ev
    return None


def _events(card: PaymentCard, name: str) -> list[dict[str, Any]]:
    return [ev for ev in card.timeline if ev.get("event") == name]


def _duration(card: PaymentCard, run: Run, step_id: str, *keys: str) -> tuple[float | None, str | None]:
    """Per-card ms when the engine measured it, else the run's node time (scope ``run``)."""
    keys = keys or (step_id,)
    if all(k in card.step_ms for k in keys):
        return sum(card.step_ms[k] for k in keys), "card"
    node = NODE_OF.get(step_id)
    if node and node in run.node_ms:
        return float(run.node_ms[node]), "run"
    return None, None


def _submission(run: Run, card: PaymentCard) -> Any:
    try:
        return run.submissions[int(card.id.rsplit(".", 1)[1]) - 1]
    except (ValueError, IndexError):
        return None


def _pct(x: float | None) -> str:
    return "?" if x is None else f"{round(float(x) * 100)}%"


# --- steps ---------------------------------------------------------------------------------------------


def _intake(card: PaymentCard, run: Run, sub: Any) -> dict[str, Any]:
    inv = card.invoice
    docs = list(getattr(sub, "documents", None) or [])
    files = [d for d in docs if d.get("kind") != "email_body"]
    source = inv.source
    if source == "email":
        tool, what = "email intake (IMAP / .eml)", "email received"
    elif source in ("upload", "pdf_text"):
        tool, what = "file upload", "upload received"
    elif source == "text":
        tool, what = "text submission", "invoice text received"
    else:
        tool, what = "JSON API", "structured fields received"
    names = ", ".join(str(d.get("filename")) for d in files[:4])
    summary = what + (f", {len(files)} file{'s' if len(files) != 1 else ''}" if files else "")
    if not files and inv.source == "email":
        summary += ", body only"
    received = getattr(sub, "received_at", None) or run.created_at
    headers = dict(getattr(sub, "headers", None) or {})
    detail = [
        f"files: {names}" if names else "",
        f"from: {headers['From']}" if headers.get("From") else "",
        f"submitted by {inv.submitted_by}",
        f"run {run.id} · {run.label}" if run.label else f"run {run.id}",
    ]
    return _step(
        "intake",
        "Intake",
        tool,
        "deterministic",
        status="ok",
        summary=summary,
        duration_ms=None,
        scope=None,
        at=received,
        detail=detail,
        files=[str(d.get("filename")) for d in files],
    )


def _format(card: PaymentCard, run: Run) -> dict[str, Any] | None:
    cls = card.intake
    failed = _event(card, "intake_classification_failed")
    if cls is None:
        if failed is None:
            return None
        return _step(
            "format",
            "Format",
            "intake classifier",
            "deterministic",
            status="failed",
            summary=f"classification failed: {failed.get('error')}",
            duration_ms=None,
            scope=None,
            at=failed.get("at"),
        )
    tool, kind = ENGINE_LABELS.get(cls.engine, (cls.engine, "model"))
    if cls.engine == "decider" and cls.decider_model:
        tool = f"Strands Decider 2B ({cls.decider_model})"
    calls = cls.decider_calls + cls.llm_calls
    conf = cls.format_confidence
    conf_text = (
        f"confidence {conf:.2f}" if isinstance(conf, int | float) else "no calibrated confidence (chat model)"
    )
    if cls.engine == "deterministic":
        why = (
            "route was obvious, so no model was asked"
            if not cls.ambiguous
            else f"ambiguous ({', '.join(cls.ambiguous)}); default route used"
        )
        cost = f"0 model calls · {why}"
    else:
        cost = f"{calls} model call{'s' if calls != 1 else ''}, {cls.model_latency_ms:.0f} ms, {cls.tokens} tokens"
    summary = f"{cls.format} → {cls.tool} · {conf_text} · {cost}"
    status: Status = "ok"
    if cls.kickback:
        status = "hold"
        summary += f" · kickback [{cls.kickback_code}] drafted for the owner"
    elif cls.review_required:
        status = "hold"
        summary += " · owner review required"
    detail = [
        f"engine {cls.engine} · INTAKE_CLASSIFIER={cls.policy} (the Decider is only asked when the route "
        "is ambiguous)",
        f"deterministic route was {cls.deterministic_format} → {cls.deterministic_tool}"
        if cls.engine != "deterministic"
        else "",
        f"extractor used: {cls.extractor_used}" if cls.extractor_used else "",
        "decided before extraction; the tool decision chose the extractor" if cls.before_extraction else "",
        f"fallback: {cls.fallback_reason}" if cls.fallback_reason else "",
        f"{cls.validation_failures} classifier output(s) failed schema validation"
        if cls.validation_failures
        else "",
    ]
    for d in cls.decisions:
        line = f"{d.key}: {d.answer or '-'} ({d.engine}"
        if d.engine != "deterministic":
            line += f", {d.latency_ms:.0f} ms"
            if d.confidence is not None:
                line += f", {d.confidence:.2f}"
        line += ")" + ("" if d.accepted else f" · rejected: {d.error or d.note}")
        detail.append(line)
    classified = _event(card, "intake_classified")
    ms = cls.model_latency_ms if calls else card.step_ms.get("format")
    return _step(
        "format",
        "Format",
        tool,
        kind,  # type: ignore[arg-type]
        status=status,
        summary=summary,
        duration_ms=ms,
        scope="card" if ms is not None else None,
        at=classified.get("at") if classified else cls.at,
        detail=detail,
        engine=cls.engine,
        confidence=conf,
        model_calls=calls,
        tokens=cls.tokens,
    )


def _read(card: PaymentCard, run: Run, sub: Any) -> dict[str, Any]:
    inv = card.invoice
    ev = _event(card, "intake_read") or {}
    llm_calls = int(ev.get("llm_calls") or 0)
    docs = list(getattr(sub, "documents", None) or [])
    extractors = []
    for d in docs:
        name = EXTRACTOR_LABELS.get(str(d.get("extractor")), str(d.get("extractor") or ""))
        if name and name not in extractors:
            extractors.append(name)
    parts = [*extractors, "kernel regex parser (plain code)"]
    if llm_calls:
        parts.append(f"intake agent ({ev.get('model') or 'LLM'}; quotes verified verbatim in the source)")
    tool = " + ".join(parts)
    kind: Kind = "llm" if llm_calls else "deterministic"
    amount = format_cents(inv.amount_cents, inv.currency) if inv.amount_cents else "no verifiable amount"
    vendor = inv.vendor_name if inv.vendor_name != "unknown vendor" else "vendor not read"
    summary = f"{amount} · {vendor} · {inv.invoice_number}"
    status: Status = "ok"
    if inv.amount_origin == "llm":
        status, summary = "flagged", summary + " · amount came from the LLM, not the source: held"
    elif inv.amount_origin == "missing" or inv.amount_cents <= 0:
        status, summary = "flagged", summary + " · held until re-keyed from the source"
    elif inv.vendor_name == "unknown vendor":
        status = "flagged"
    notes = [str(e.get("note")) for e in _events(card, "intake_note")]
    detail = [
        f"amount origin: {inv.amount_origin}",
        f"due {inv.due_date.isoformat()} · issued {inv.issue_date.isoformat()}",
        f"PO {inv.po_number}" if inv.po_number else "no purchase order",
        f"bank on invoice ****{inv.bank_account[-4:]}" if inv.bank_account else "",
        f"{llm_calls} LLM call(s) in this step" if llm_calls else "0 LLM calls in this step",
        *notes,
    ]
    ms, scope = _duration(card, run, "read")
    return _step(
        "read",
        "Read",
        tool,
        kind,
        status=status,
        summary=summary,
        duration_ms=ms,
        scope=scope,
        at=ev.get("at"),
        detail=detail,
        llm_calls=llm_calls,
    )


def _screen(card: PaymentCard, run: Run) -> dict[str, Any] | None:
    res = card.resolution
    if res is None:
        return None
    matched = list(res.matched_on)
    if res.embedding_used:
        tool = "vendor resolver + pgvector / hackathon-embedding re-rank"
        kind: Kind = "model"
    else:
        tool = "vendor resolver (tax id, domain, fuzzy name, bank account)"
        kind = "deterministic"
    if res.status == "known":
        how = ", ".join(m.replace("_", " ") for m in matched) or "exact id"
        summary = f"known vendor {res.vendor_name} · resolved by {how} · confidence {res.confidence:.2f}"
        status: Status = "ok"
    elif res.status == "uncertain":
        top = res.candidates[0] if res.candidates else None
        summary = "ambiguous match" + (
            f" · closest {top.name} ({top.matched_on.replace('_', ' ')} {top.score:.2f})" if top else ""
        )
        status = "flagged"
    else:
        summary = f"{res.vendor_name}: not on the master file (new vendor)"
        status = "flagged"
    ev = _event(card, "vendor_resolved") or {}
    ms, scope = _duration(card, run, "screen")
    detail = [
        *(f"candidate {c.name} · {c.matched_on.replace('_', ' ')} {c.score:.2f}" for c in res.candidates[:4]),
        *res.notes,
    ]
    return _step(
        "screen",
        "Screen",
        tool,
        kind,
        status=status,
        summary=summary,
        duration_ms=ms,
        scope=scope,
        at=ev.get("at"),
        detail=detail,
        match=res.status,
        matched_on=matched,
        confidence=res.confidence,
    )


def _check(card: PaymentCard, run: Run) -> dict[str, Any] | None:
    ch = card.checks
    sender = card.sender
    if not ch and not (sender and sender.checked):
        return None
    checks: list[str] = []
    if sender and sender.checked:
        checks.append("sender check")
    checks += ["amount kernel", "bank change", "duplicate / split", "ring graph"]
    tool = " · ".join(checks) + " (plain code)"
    detail: list[str] = []
    if sender and sender.checked:
        detail.append(
            "sender: "
            + ("SPF/DKIM/DMARC pass" if sender.auth_pass else "authentication not verified")
            + (f" · {', '.join(sender.flags)}" if sender.flags else "")
        )
    if ch:
        if ch.get("history_median_cents"):
            detail.append(
                f"amount: {ch['amount_ratio_milli'] / 1000:.1f}x the usual "
                f"{format_cents(int(ch['history_median_cents']))} over {ch.get('history_count', 0)} payments"
            )
        else:
            detail.append("amount: no payment history to compare against")
        if ch.get("near_approval_limit"):
            detail.append("amount: just under the approval limit")
        if ch.get("bank_mismatch"):
            detail.append("bank: account on the invoice differs from the master file")
        elif ch.get("bank_change_recent"):
            detail.append(
                "bank: changed recently"
                + (" · confirmed out-of-band" if ch.get("bank_change_confirmed") else " · not confirmed")
            )
        else:
            detail.append(
                "bank: matches the master file" if ch.get("vendor_found") else "bank: no vendor on file"
            )
        if ch.get("duplicate_of"):
            detail.append(f"duplicate: {ch['duplicate_of']}")
        elif ch.get("split_group"):
            detail.append(
                f"split: {len(ch['split_group'])} invoices total {format_cents(int(ch.get('split_total_cents') or 0))}"
            )
        else:
            detail.append("duplicate / split: none")
        shared = ch.get("shared_attributes") or {}
        if shared:
            for attr, others in shared.items():
                detail.append(f"ring: {attr.replace('_', ' ')} shared with {len(others)} other vendor(s)")
        else:
            detail.append("ring: no shared bank, phone or address")
        if ch.get("injection"):
            detail.append(f"injection: {len(ch['injection'])} instruction(s) aimed at the system")
    flags = list(card.flags)
    if sender and sender.checked and sender.flags:
        flags = [f"sender: {f.replace('_', ' ')}" for f in sender.flags] + flags
    if flags:
        shared = ch.get("shared_attributes") or {}
        headline = flags[0]
        if shared:
            attr, others = next(iter(shared.items()))
            headline = f"{attr.replace('_', ' ')} shared by {len(others) + 1} vendors"
        summary = f"{headline} · flagged" + (f" · {len(flags) - 1} more" if len(flags) > 1 else "")
        status: Status = "flagged"
    else:
        summary = f"clean · {len(checks)} checks passed"
        status = "ok"
    ev = _event(card, "kernel_checked") or _event(card, "sender_checked") or {}
    keys = ("sender", "check") if "sender" in card.step_ms else ("check",)
    ms, scope = _duration(card, run, "check", *keys)
    if scope == "run" and "sender" in run.node_ms:
        ms = (ms or 0.0) + float(run.node_ms["sender"])
    return _step(
        "check",
        "Check",
        tool,
        "deterministic",
        status=status,
        summary=summary,
        duration_ms=ms,
        scope=scope,
        at=ev.get("at"),
        detail=detail,
        flags=flags,
    )


def _score(card: PaymentCard, run: Run) -> dict[str, Any] | None:
    s = card.scores
    if s is None:
        return None
    tool, kind = SCORER_LABELS.get(s.scorer, (s.scorer, "model"))
    if s.model_version and kind == "model":
        tool = f"{tool} {s.model_version}"
    top_p = s.risk.get(s.top_class)
    lime = [str(item.get("label") or item.get("feature")) for item in s.lime[:3]]
    summary = f"{s.top_class} {top_p:.2f}" if top_p is not None else s.top_class
    summary += f" · legitimacy {_pct(s.legitimacy)}"
    if lime:
        summary += f" · LIME: {lime[0]}"
    status: Status = "flagged" if s.legitimacy < 0.5 else "ok"
    ev = _event(card, "scored") or {}
    scored = sum(1 for c in run.card_list() if c.scores)
    ms, scope = _duration(card, run, "score")
    detail = [
        " · ".join(f"{k} {v:.2f}" for k, v in sorted(s.risk.items(), key=lambda kv: -kv[1])),
        f"anomaly percentile {_pct(s.anomaly)}"
        + (f" · ring score {s.ring_score:.2f}" if s.ring_score else ""),
        *(f"LIME {i}: {label}" for i, label in enumerate(lime, start=1)),
        f"scored in one batch of {scored} card(s)" if scope == "run" else "",
    ]
    return _step(
        "score",
        "Score",
        tool,
        kind,  # type: ignore[arg-type]
        status=status,
        summary=summary,
        duration_ms=ms,
        scope=scope,
        at=ev.get("at"),
        detail=detail,
        top_class=s.top_class,
        legitimacy=s.legitimacy,
    )


def _investigate(card: PaymentCard, run: Run) -> dict[str, Any] | None:
    inv = card.investigation
    if inv is None:
        return None
    llm = inv.source == "llm"
    tool = (
        f"{inv.investigator} investigator agent (hackathon-chat)" if llm else f"{inv.investigator} template"
    )
    rejected = _event(card, "provenance_rejected")
    detail = [
        f"recommended action: {inv.recommended_action.replace('_', ' ')}",
        *inv.vendor_questions[:3],
        "LLM report failed the provenance check; template used"
        if rejected and rejected.get("role") == "investigator"
        else "",
    ]
    ev = _event(card, "investigated") or {}
    ms, scope = _duration(card, run, "investigate")
    return _step(
        "investigate",
        "Investigate",
        tool,
        "llm" if llm else "deterministic",
        status="flagged",
        summary=inv.summary,
        duration_ms=ms,
        scope=scope,
        at=ev.get("at"),
        detail=detail,
    )


def _policy(engine: VouchEngine, card: PaymentCard, run: Run) -> dict[str, Any] | None:
    p = card.policy
    if p is None:
        return None
    from vouch.policy import PaymentAttrs, authorize, cedar_available
    from vouch.views import lifecycle_of, risk_of, trust_score, vouch_status

    ch = card.checks
    attrs = PaymentAttrs(
        status=vouch_status(card),
        lifecycle=lifecycle_of(card),
        risk=risk_of(card),
        trust_score=trust_score(card),
        fast_pay_eligible=p.lane == Lane.FAST_PAY,
        bank_changed=bool(ch.get("bank_mismatch") or ch.get("bank_change_recent")),
        bank_change_verified=bool(ch.get("bank_change_confirmed") or card.has_resolution("confirm_bank")),
        amount_cents=card.payable_cents,
        vendor_known=card.vendor is not None,
    )
    hold = authorize("System", "hold", attrs, payment_id=card.id)
    model_settle = authorize("Model", "settle", attrs, payment_id=card.id)
    model_approve = authorize("Model", "approve", attrs, payment_id=card.id)
    cedar = cedar_available()
    tool = "Cedar default-deny (cedarpy)" if cedar else "Cedar default-deny (Python mirror of vouch.cedar)"
    lane = p.lane.value.replace("_", " ")
    summary = f"lane {lane}"
    if p.lane == Lane.HOLD:
        summary += f" · {p.reasons[0]}" if p.reasons else ""
        status: Status = "hold"
    else:
        status = "ok"
    summary += (
        f" · hold {'permitted' if hold.allowed else 'denied'} for the system"
        f" · approve/settle {'denied' if not (model_approve.allowed or model_settle.allowed) else 'PERMITTED'} "
        "for the agent"
    )
    ev = _events(card, "policy")
    ms, scope = _duration(card, run, "policy")
    detail = [
        *(f"reason: {r}" for r in p.reasons),
        *(f"next step: {a}" for a in p.required_actions),
        f"System hold → {', '.join(hold.reasons)}",
        f"Model settle → {', '.join(model_settle.reasons)} · Model approve → {', '.join(model_approve.reasons)}",
        f"re-evaluated {len(ev)}x (owner actions re-run the policy)" if len(ev) > 1 else "",
    ]
    return _step(
        "policy",
        "Policy",
        tool,
        "deterministic",
        status=status,
        summary=summary,
        duration_ms=ms,
        scope=scope,
        at=ev[-1].get("at") if ev else None,
        detail=detail,
        lane=p.lane.value,
        policy_engine="cedar" if cedar else "python-mirror",
        agent_denied=not (model_approve.allowed or model_settle.allowed),
    )


def _writer(engine: VouchEngine, card: PaymentCard, run: Run) -> dict[str, Any] | None:
    if card.explanation_source == "pending" and not card.explanation:
        return None
    llm = card.explanation_source == "llm"
    rejected = next((e for e in _events(card, "provenance_rejected") if e.get("role") == "explainer"), None)
    if llm:
        tool = f"explainer agent ({engine.llm.model_name}; provenance-checked)"
    elif rejected:
        tool = "template explainer (LLM draft rejected by the provenance check)"
    else:
        tool = "template explainer (plain code)"
    text = card.explanation or ""
    summary = text if len(text) <= 140 else text[:137].rstrip() + "…"
    detail = [
        text if len(text) > 140 else "",
        f"source: {card.explanation_source}",
        f"rejected claims not in the fact sheet: {', '.join(map(str, rejected.get('unknown') or []))}"
        if rejected
        else "",
    ]
    ms, scope = _duration(card, run, "writer")
    return _step(
        "writer",
        "Writer",
        tool,
        "llm" if llm else "deterministic",
        status="ok",
        summary=summary,
        duration_ms=ms,
        scope=scope,
        at=None,
        detail=detail,
        source=card.explanation_source,
    )


_RESOLUTION_LABELS = {
    "approve": "approved",
    "owner_hold": "held",
    "release_hold": "hold released",
    "appeal": "appeal recorded",
    "resolve_risk": "risk resolved",
    "confirm_bank": "bank change confirmed by call-back",
    "limit_override": "limit override",
}


def _approval(card: PaymentCard, run: Run) -> dict[str, Any] | None:
    if card.status == CardStatus.CREDIT or card.policy is None:
        return None
    actions = list(card.resolutions)
    approve = next((r for r in actions if r.kind == "approve"), None)
    detail = [
        f"{_RESOLUTION_LABELS.get(r.kind, r.kind)} by {r.actor}"
        + (f" · {r.note}" if r.note else "")
        + (f" · {r.method}" if r.method else "")
        for r in actions
    ]
    if approve is not None or card.status in (CardStatus.APPROVED, CardStatus.PAID):
        who = approve.actor if approve else "owner"
        summary = f"approved by {who}"
        if card.policy.lane == Lane.FAST_PAY and approve is None:
            summary = "fast-pay under the owner's standing rule (no per-invoice approval)"
        status: Status = "ok"
        at = approve.at if approve else None
    elif card.status == CardStatus.HOLD:
        step = card.policy.required_actions[0] if card.policy.required_actions else "owner review"
        summary = f"waiting: on hold until {step}"
        status = "hold"
        at = actions[-1].at if actions else None
    elif run.pending is not None:
        summary = "waiting for the owner · graph paused at the approval interrupt"
        status = "pending"
        at = None
    else:
        summary = "waiting for the owner"
        status = "pending"
        at = actions[-1].at if actions else None
    return _step(
        "approval",
        "Owner approval",
        "owner (human in the loop)",
        "human",
        status=status,
        summary=summary,
        duration_ms=None,
        scope=None,
        at=at,
        detail=detail,
    )


def _settlement(engine: VouchEngine, card: PaymentCard, run: Run) -> dict[str, Any] | None:
    receipt = card.receipt
    failed = _event(card, "settlement_failed")
    paid = _event(card, "paid")
    if receipt is None and failed is None:
        if card.status == CardStatus.APPROVED:
            when = (card.funding or {}).get("pay_on")
            return _step(
                "settlement",
                "Settlement",
                f"{engine.adapter.name} · {engine.adapter.network}",
                "deterministic",
                status="pending",
                summary=f"scheduled for {when}" if when else "waiting for the batch",
                duration_ms=None,
                scope=None,
            )
        return None
    network = str((receipt or {}).get("network") or engine.adapter.network)
    adapter = next((s.get("adapter") for s in run.settlements if s.get("payments")), engine.adapter.name)
    if adapter == "xrpl" or "xrpl" in network.lower():
        tool = f"XRPL testnet ({network})"
    elif adapter == "mock":
        tool = "mock ledger (simulated)"
    else:
        tool = f"{adapter} · {network}"
    ms, scope = _duration(card, run, "settlement", "settle")
    if scope == "card":
        scope = "batch"
    if receipt and str(receipt.get("status")) == "settled":
        tx = str(receipt.get("tx_id") or "")
        summary = f"tx {tx[:12]}{'…' if len(tx) > 12 else ''} · {format_cents(card.payable_cents, card.invoice.currency)}"
        status: Status = "ok"
    else:
        summary = f"failed: {(failed or {}).get('error') or (receipt or {}).get('status')}"
        status = "failed"
    lane = (paid or {}).get("lane")
    detail = [
        f"lane {str(lane).replace('_', ' ')}" if lane else "",
        f"batch tx {receipt['batch_tx_id']}" if receipt and receipt.get("batch_tx_id") else "",
        f"explorer {receipt['explorer_url']}" if receipt and receipt.get("explorer_url") else "",
        f"idempotency key {receipt['idempotency_key']}" if receipt and receipt.get("idempotency_key") else "",
    ]
    return _step(
        "settlement",
        "Settlement",
        tool,
        "deterministic",
        status=status,
        summary=summary,
        duration_ms=ms,
        scope=scope,
        at=(paid or failed or {}).get("at"),
        detail=detail,
        tx_id=(receipt or {}).get("tx_id"),
        explorer_url=(receipt or {}).get("explorer_url"),
    )


def steps_of(engine: VouchEngine, run: Run, card: PaymentCard) -> list[dict[str, Any]]:
    """The orchestrator timeline for one card: only steps that ran, in the order they ran."""
    sub = _submission(run, card)
    fmt = _format(card, run)
    read = _read(card, run, sub)
    # The live intake service settles the routing chain before extraction; text-only submissions are
    # classified after the kernel parsed them.
    before = bool(card.intake and card.intake.before_extraction)
    ordered: list[dict[str, Any] | None] = [
        _intake(card, run, sub),
        *([fmt, read] if before else [read, fmt]),
        _screen(card, run),
        _check(card, run),
        _score(card, run),
        _investigate(card, run),
        _policy(engine, card, run),
        _writer(engine, card, run),
        _approval(card, run),
        _settlement(engine, card, run),
    ]
    steps = [s for s in ordered if s is not None]
    for i, s in enumerate(steps, start=1):
        s["seq"] = i
    return steps


__all__ = ["steps_of"]
