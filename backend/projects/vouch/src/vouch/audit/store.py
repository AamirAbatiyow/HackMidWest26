"""Audit records: vendors, runs, payment cards, decisions, policy results, approvals, settlements,
intake documents and the embedding cache.

Postgres (Akamai Managed PostgreSQL) when ``DATABASE_URL`` is set and reachable; a SQLite file otherwise
(``VOUCH_DATA_DIR/vouch.sqlite3``); ``sqlite://`` for in-memory tests. The engine's state (runs + cards +
vendor master) is written after every graph node and owner action and loaded back at startup, so a
restart never loses a hold, an approval or a settlement receipt.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, create_engine, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from ..cards import PaymentCard
from ..domain import Vendor

log = logging.getLogger(__name__)


def now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class Base(DeclarativeBase):
    pass


class VendorRow(Base):
    __tablename__ = "vendors"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    data: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class RunRow(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[str] = mapped_column(String(40))
    llm_mode: Mapped[str] = mapped_column(String(16), default="offline")
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    data: Mapped[dict] = mapped_column(JSON)  # events, node_ms, settlements, approval, pending, error
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class CardRow(Base):
    __tablename__ = "payment_cards"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    vendor_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    lane: Mapped[str | None] = mapped_column(String(16), nullable=True)
    data: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class DecisionRow(Base):
    __tablename__ = "decisions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    card_id: Mapped[str] = mapped_column(String(64), index=True)
    lane: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    reasons: Mapped[list] = mapped_column(JSON)
    scorer: Mapped[str | None] = mapped_column(String(40), nullable=True)
    legitimacy: Mapped[float | None] = mapped_column(nullable=True)
    lime: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PolicyRow(Base):
    __tablename__ = "policy_results"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    card_id: Mapped[str] = mapped_column(String(64), index=True)
    engine: Mapped[str] = mapped_column(String(32))
    principal: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64))
    allowed: Mapped[bool] = mapped_column(Boolean)
    reasons: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ApprovalRow(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    card_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(24))
    note: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(80), default="owner")
    policy_rule: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SettlementRow(Base):
    __tablename__ = "settlements"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # batch id
    run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    tx_id: Mapped[str] = mapped_column(String(120))
    explorer_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    card_ids: Mapped[list] = mapped_column(JSON)
    total_cents: Mapped[int] = mapped_column(Integer)
    funding: Mapped[str] = mapped_column(String(16), default="now")
    scheduled_for: Mapped[str | None] = mapped_column(String(40), nullable=True)
    adapter: Mapped[str] = mapped_column(String(24), default="mock")
    network: Mapped[str] = mapped_column(String(60), default="mock")
    lane: Mapped[str] = mapped_column(String(16), default="standard")
    payments: Mapped[list] = mapped_column(JSON, default=list)
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DocumentRow(Base):
    __tablename__ = "intake_documents"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    card_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    extractor: Mapped[str] = mapped_column(String(40))
    # The chain's tool decision and, when the default extractor ran instead of that tool's, why.
    tool: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fallback: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    text_excerpt: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class IntakeDecisionRow(Base):
    """One row per decision-classifier question (format / tool / kickback reason), rejected attempts
    included: what was asked, what was offered, what was chosen, who decided and what it cost."""

    __tablename__ = "intake_decisions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    card_id: Mapped[str] = mapped_column(String(64), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    key: Mapped[str] = mapped_column(String(32))
    question: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON)
    answer: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    accepted: Mapped[bool] = mapped_column(Boolean)
    engine: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    latency_ms: Mapped[float] = mapped_column(default=0.0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    validation_errors: Mapped[list] = mapped_column(JSON, default=list)  # SDK-rejected structured outputs
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class KickbackDraftRow(Base):
    """The kickback outbox: drafted replies to senders. The owner approves or declines (P-08); ``sent_at``
    stays NULL until the owner hands the approved draft to the mail integration (P-09)."""

    __tablename__ = "kickback_drafts"
    card_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    to: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text, default="")
    missing_fields: Mapped[list] = mapped_column(JSON, default=list)
    chosen_by: Mapped[str] = mapped_column(String(32), default="deterministic")
    status: Mapped[str] = mapped_column(String(16), default="awaiting_owner", index=True)
    decided_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sent_via: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EmbeddingCacheRow(Base):
    __tablename__ = "embedding_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    vector: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        if url in ("sqlite://", "sqlite:///:memory:"):
            return create_engine(
                url, connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
            )
        return create_engine(url, connect_args={"check_same_thread": False}, future=True)
    return create_engine(url, pool_pre_ping=True, future=True)


def _json(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=str))


def _ensure_columns(engine: Engine) -> None:
    """Add columns this version declares on tables an older deployment already created.

    ``create_all`` only creates missing tables. Columns are added without NOT NULL so existing rows stay
    valid; new rows always carry the Python-side defaults.
    """
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}"
                log.info("audit store: %s", ddl)
                conn.execute(text(ddl))


class AuditStore:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine = make_engine(url)
        Base.metadata.create_all(self.engine)
        _ensure_columns(self.engine)

    @classmethod
    def open(cls, url: str, fallback_url: str | None = None) -> AuditStore:
        """Open `url`; if it is unreachable (e.g. Postgres not running locally) fall back to SQLite."""
        try:
            store = cls(url)
            ok, detail = store.ping()
            if ok:
                return store
            raise RuntimeError(detail)
        except Exception as exc:
            if not fallback_url or fallback_url == url:
                raise
            log.warning("audit store %s unavailable (%s); using %s", _redact(url), exc, fallback_url)
            return cls(fallback_url)

    @property
    def backend(self) -> str:
        if self.url.startswith("postgresql"):
            return "postgres"
        return "sqlite-memory" if self.url in ("sqlite://", "sqlite:///:memory:") else "sqlite"

    def session(self) -> Session:
        return Session(self.engine, expire_on_commit=False)

    def ping(self) -> tuple[bool, str]:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                version = ""
                if self.backend == "postgres":
                    version = str(conn.execute(text("SHOW server_version")).scalar() or "")
                    ext = conn.execute(
                        text("SELECT extversion FROM pg_extension WHERE extname='vector'")
                    ).scalar()
                    version += f" · pgvector {ext}" if ext else " · pgvector not installed"
            return True, f"{self.backend} {version}".strip()
        except Exception as exc:
            return False, f"{type(exc).__name__}: {str(exc)[:120]}"

    # ---- vendor master -----------------------------------------------------

    def save_vendors(self, vendors: list[Vendor]) -> None:
        with self.session() as s:
            for v in vendors:
                data = json.loads(v.model_dump_json())
                row = s.get(VendorRow, v.id)
                if row is None:
                    s.add(VendorRow(id=v.id, name=v.name, data=data))
                else:
                    row.name, row.data = v.name, data
            s.commit()

    def load_vendors(self) -> list[Vendor]:
        with self.session() as s:
            return [Vendor.model_validate(r.data) for r in s.execute(select(VendorRow)).scalars().all()]

    # ---- engine state: runs + cards ---------------------------------------

    def save_run(self, run: Any, llm_mode: str = "offline", model: str | None = None) -> None:
        """`run` is a `vouch.engine.Run`; its cards are stored one row each."""
        data = {
            "submissions": [sub.model_dump(mode="json") for sub in run.submissions],
            "events": run.events,
            "node_ms": run.node_ms,
            "settlements": run.settlements,
            "approval": run.approval,
            "pending": run.pending,
            "error": run.error,
        }
        with self.session() as s:
            row = s.get(RunRow, run.id)
            if row is None:
                s.add(
                    RunRow(
                        id=run.id,
                        label=run.label,
                        status=run.status,
                        created_at=run.created_at,
                        llm_mode=llm_mode,
                        model=model,
                        data=_json(data),
                    )
                )
            else:
                row.status, row.label, row.data = run.status, run.label, _json(data)
            for card in run.card_list():
                self._upsert_card(s, card)
            s.commit()

    def _upsert_card(self, s: Session, card: PaymentCard) -> None:
        data = json.loads(card.model_dump_json())
        row = s.get(CardRow, card.id)
        lane = card.policy.lane.value if card.policy else None
        if row is None:
            s.add(
                CardRow(
                    id=card.id,
                    run_id=card.run_id,
                    vendor_id=card.invoice.vendor_id,
                    status=card.status.value,
                    lane=lane,
                    data=data,
                )
            )
        else:
            row.vendor_id, row.status, row.lane, row.data = (
                card.invoice.vendor_id,
                card.status.value,
                lane,
                data,
            )

    def load_runs(self) -> list[dict[str, Any]]:
        """Runs with their cards, oldest first. The caller rebuilds `Run` objects (graph state is not kept)."""
        with self.session() as s:
            runs = s.execute(select(RunRow).order_by(RunRow.created_at)).scalars().all()
            cards = s.execute(select(CardRow).order_by(CardRow.id)).scalars().all()
        by_run: dict[str, list[PaymentCard]] = {}
        for c in cards:
            by_run.setdefault(c.run_id, []).append(PaymentCard.model_validate(c.data))
        return [
            {
                "id": r.id,
                "label": r.label,
                "status": r.status,
                "created_at": r.created_at,
                **r.data,
                "cards": by_run.get(r.id, []),
            }
            for r in runs
        ]

    def delete_runs(self, run_ids: list[str]) -> None:
        if not run_ids:
            return
        with self.session() as s:
            for rid in run_ids:
                for c in s.execute(select(CardRow).where(CardRow.run_id == rid)).scalars().all():
                    s.delete(c)
                row = s.get(RunRow, rid)
                if row is not None:
                    s.delete(row)
            s.commit()

    def delete_all_runs(self) -> None:
        with self.session() as s:
            s.query(CardRow).delete()
            s.query(RunRow).delete()
            s.commit()

    # ---- audit trail ---------------------------------------------------------

    def record_decision(self, card: PaymentCard) -> None:
        if card.policy is None:
            return
        with self.session() as s:
            s.add(
                DecisionRow(
                    id=new_id("dec"),
                    run_id=card.run_id,
                    card_id=card.id,
                    lane=card.policy.lane.value,
                    status=card.status.value,
                    reasons=list(card.policy.reasons),
                    scorer=card.scores.scorer if card.scores else None,
                    legitimacy=card.scores.legitimacy if card.scores else None,
                    lime=_json(card.scores.lime[:6]) if card.scores else [],
                )
            )
            s.commit()

    def record_policy(
        self,
        run_id: str | None,
        card_id: str,
        engine: str,
        principal: str,
        action: str,
        allowed: bool,
        reasons: list[str],
    ) -> None:
        with self.session() as s:
            s.add(
                PolicyRow(
                    id=new_id("pol"),
                    run_id=run_id,
                    card_id=card_id,
                    engine=engine,
                    principal=principal,
                    action=action,
                    allowed=allowed,
                    reasons=list(reasons),
                )
            )
            s.commit()

    def record_approval(
        self, card_id: str, action: str, note: str, author: str, policy_rule: str | None = None
    ) -> str:
        aid = new_id("apr")
        with self.session() as s:
            s.add(
                ApprovalRow(
                    id=aid, card_id=card_id, action=action, note=note, author=author, policy_rule=policy_rule
                )
            )
            s.commit()
        return aid

    def has_owner_approval(self, card_id: str) -> bool:
        with self.session() as s:
            row = s.execute(
                select(ApprovalRow).where(ApprovalRow.card_id == card_id, ApprovalRow.action == "approve")
            ).first()
            return row is not None

    def record_settlement(
        self,
        batch_id: str,
        run_id: str | None,
        tx_id: str,
        explorer_url: str | None,
        card_ids: list[str],
        total_cents: int,
        funding: str,
        scheduled_for: str | None,
        adapter: str,
        network: str,
        lane: str,
        payments: list[dict[str, Any]],
    ) -> None:
        with self.session() as s:
            if s.get(SettlementRow, batch_id) is not None:
                return
            s.add(
                SettlementRow(
                    id=batch_id,
                    run_id=run_id,
                    tx_id=tx_id,
                    explorer_url=explorer_url,
                    card_ids=card_ids,
                    total_cents=total_cents,
                    funding=funding,
                    scheduled_for=scheduled_for,
                    adapter=adapter,
                    network=network,
                    lane=lane,
                    payments=_json(payments),
                )
            )
            s.commit()

    def settlements(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = (
                s.execute(select(SettlementRow).order_by(SettlementRow.settled_at.desc()).limit(limit))
                .scalars()
                .all()
            )
            return [
                {
                    "batch_id": r.id,
                    "run_id": r.run_id,
                    "tx_id": r.tx_id,
                    "explorer_url": r.explorer_url,
                    "card_ids": r.card_ids,
                    "total_cents": r.total_cents,
                    "funding": r.funding,
                    "scheduled_for": r.scheduled_for,
                    "adapter": r.adapter,
                    "network": r.network,
                    "lane": r.lane,
                    "payments": r.payments,
                    "settled_at": r.settled_at.isoformat(),
                }
                for r in rows
            ]

    def record_document(
        self,
        run_id: str | None,
        card_id: str | None,
        filename: str,
        kind: str,
        sha256: str,
        extractor: str,
        text_excerpt: str,
        storage_key: str | None,
        *,
        tool: str | None = None,
        fallback: str | None = None,
    ) -> None:
        with self.session() as s:
            s.add(
                DocumentRow(
                    id=new_id("doc"),
                    run_id=run_id,
                    card_id=card_id,
                    filename=filename,
                    kind=kind,
                    sha256=sha256,
                    extractor=extractor,
                    tool=tool,
                    fallback=fallback,
                    text_excerpt=text_excerpt[:4000],
                    storage_key=storage_key,
                )
            )
            s.commit()

    # ---- intake decision classifiers + kickback outbox ----------------------

    def record_intake_decisions(self, card: PaymentCard) -> int:
        """Persist the card's decision chain once (idempotent per card); returns the rows written."""
        cls = card.intake
        if cls is None or not cls.decisions:
            return 0
        with self.session() as s:
            existing = s.execute(
                select(IntakeDecisionRow.id).where(IntakeDecisionRow.card_id == card.id)
            ).first()
            if existing is not None:
                return 0
            for i, d in enumerate(cls.decisions):
                s.add(
                    IntakeDecisionRow(
                        id=new_id("dec"),
                        run_id=card.run_id,
                        card_id=card.id,
                        seq=i,
                        key=d.key,
                        question=d.question,
                        options=list(d.options),
                        answer=d.answer,
                        reason_code=d.reason_code,
                        accepted=bool(d.accepted),
                        engine=d.engine,
                        confidence=d.confidence,
                        latency_ms=float(d.latency_ms),
                        input_tokens=int(d.input_tokens),
                        output_tokens=int(d.output_tokens),
                        attempts=int(d.attempts),
                        validation_errors=list(d.validation_errors),
                        error=d.error,
                        note=d.note,
                    )
                )
            s.commit()
            return len(cls.decisions)

    def save_kickback_draft(self, card: PaymentCard) -> None:
        """Upsert the card's kickback draft in the outbox (status, decision and note follow the card)."""
        cls = card.intake
        draft = cls.kickback_draft if cls else None
        if draft is None:
            return
        with self.session() as s:
            row = s.get(KickbackDraftRow, card.id)
            decided_at = datetime.fromisoformat(draft.decided_at) if draft.decided_at else None
            sent_at = datetime.fromisoformat(draft.sent_at) if draft.sent_at else None
            if row is None:
                row = KickbackDraftRow(
                    card_id=card.id,
                    run_id=card.run_id,
                    to=draft.to,
                    subject=draft.subject,
                    body=draft.body,
                    code=draft.code,
                    reason=draft.reason,
                    missing_fields=list(draft.missing_fields),
                    chosen_by=draft.chosen_by,
                )
                s.add(row)
            row.status, row.decided_by, row.decided_at, row.note = (
                draft.status,
                draft.decided_by,
                decided_at,
                draft.note,
            )
            row.sent_at, row.sent_by, row.sent_via, row.message_id = (
                sent_at,
                draft.sent_by,
                draft.sent_via,
                draft.message_id,
            )
            s.commit()

    def kickback_drafts(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.session() as s:
            q = select(KickbackDraftRow).order_by(KickbackDraftRow.created_at.desc()).limit(limit)
            if status:
                q = q.where(KickbackDraftRow.status == status)
            return [_draft_dict(r) for r in s.execute(q).scalars().all()]

    def intake_decisions(self, card_id: str) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = (
                s.execute(
                    select(IntakeDecisionRow)
                    .where(IntakeDecisionRow.card_id == card_id)
                    .order_by(IntakeDecisionRow.seq)
                )
                .scalars()
                .all()
            )
            return [_decision_dict(r) for r in rows]

    def embedding_lookup(self, key: str) -> list[float] | None:
        with self.session() as s:
            row = s.get(EmbeddingCacheRow, key)
            return list(row.vector) if row else None

    def embedding_persist(self, key: str, text_value: str, vector: list[float]) -> None:
        with self.session() as s:
            if s.get(EmbeddingCacheRow, key) is None:
                s.add(EmbeddingCacheRow(key=key, text=text_value, vector=vector))
                s.commit()

    def counts(self) -> dict[str, int]:
        with self.session() as s:
            return {
                "vendors": s.query(VendorRow).count(),
                "runs": s.query(RunRow).count(),
                "payment_cards": s.query(CardRow).count(),
                "decisions": s.query(DecisionRow).count(),
                "policy_results": s.query(PolicyRow).count(),
                "approvals": s.query(ApprovalRow).count(),
                "settlements": s.query(SettlementRow).count(),
                "documents": s.query(DocumentRow).count(),
                "intake_decisions": s.query(IntakeDecisionRow).count(),
                "kickback_drafts": s.query(KickbackDraftRow).count(),
                "embedding_cache": s.query(EmbeddingCacheRow).count(),
            }

    def audit_trail(self, card_id: str) -> dict[str, Any]:
        with self.session() as s:
            decisions = s.execute(select(DecisionRow).where(DecisionRow.card_id == card_id)).scalars().all()
            policies = s.execute(select(PolicyRow).where(PolicyRow.card_id == card_id)).scalars().all()
            approvals = s.execute(select(ApprovalRow).where(ApprovalRow.card_id == card_id)).scalars().all()
            docs = s.execute(select(DocumentRow).where(DocumentRow.card_id == card_id)).scalars().all()
            settlements = [
                r for r in s.execute(select(SettlementRow)).scalars().all() if card_id in (r.card_ids or [])
            ]
            decisions_rows = (
                s.execute(
                    select(IntakeDecisionRow)
                    .where(IntakeDecisionRow.card_id == card_id)
                    .order_by(IntakeDecisionRow.seq)
                )
                .scalars()
                .all()
            )
            draft = s.get(KickbackDraftRow, card_id)
            return {
                "intake_decisions": [_decision_dict(r) for r in decisions_rows],
                "kickback_draft": _draft_dict(draft) if draft else None,
                "decisions": [
                    {
                        "id": d.id,
                        "run_id": d.run_id,
                        "lane": d.lane,
                        "status": d.status,
                        "reasons": d.reasons,
                        "scorer": d.scorer,
                        "legitimacy": d.legitimacy,
                        "lime": d.lime,
                        "at": d.created_at.isoformat(),
                    }
                    for d in decisions
                ],
                "policy_results": [
                    {
                        "principal": p.principal,
                        "action": p.action,
                        "allowed": p.allowed,
                        "reasons": p.reasons,
                        "engine": p.engine,
                        "at": p.created_at.isoformat(),
                    }
                    for p in policies
                ],
                "approvals": [
                    {
                        "id": a.id,
                        "action": a.action,
                        "note": a.note,
                        "author": a.author,
                        "policy_rule": a.policy_rule,
                        "at": a.created_at.isoformat(),
                    }
                    for a in approvals
                ],
                "settlements": [
                    {
                        "batch_id": r.id,
                        "tx_id": r.tx_id,
                        "explorer_url": r.explorer_url,
                        "network": r.network,
                        "adapter": r.adapter,
                        "total_cents": r.total_cents,
                        "settled_at": r.settled_at.isoformat(),
                    }
                    for r in settlements
                ],
                "documents": [
                    {
                        "filename": d.filename,
                        "kind": d.kind,
                        "sha256": d.sha256,
                        "extractor": d.extractor,
                        "tool": d.tool,
                        "fallback": d.fallback,
                        "storage_key": d.storage_key,
                    }
                    for d in docs
                ],
            }

    def reset(self) -> None:
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)


def _decision_dict(r: IntakeDecisionRow) -> dict[str, Any]:
    return {
        "id": r.id,
        "run_id": r.run_id,
        "card_id": r.card_id,
        "seq": r.seq,
        "key": r.key,
        "question": r.question,
        "options": r.options,
        "answer": r.answer,
        "reason_code": r.reason_code,
        "accepted": r.accepted,
        "engine": r.engine,
        "confidence": r.confidence,
        "latency_ms": r.latency_ms,
        "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens,
        "attempts": r.attempts,
        "validation_errors": list(r.validation_errors or []),
        "error": r.error,
        "note": r.note,
        "at": r.created_at.isoformat(),
    }


def _draft_dict(r: KickbackDraftRow) -> dict[str, Any]:
    return {
        "card_id": r.card_id,
        "run_id": r.run_id,
        "to": r.to,
        "subject": r.subject,
        "body": r.body,
        "code": r.code,
        "reason": r.reason,
        "missing_fields": r.missing_fields,
        "chosen_by": r.chosen_by,
        "status": r.status,
        "decided_by": r.decided_by,
        "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        "note": r.note,
        "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        "sent_by": r.sent_by,
        "sent_via": r.sent_via,
        "message_id": r.message_id,
        "created_at": r.created_at.isoformat(),
    }


def _redact(url: str) -> str:
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        return f"{scheme}://***@{rest.rsplit('@', 1)[-1]}"
    return url
