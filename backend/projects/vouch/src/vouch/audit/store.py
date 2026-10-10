"""Audit records: runs, decisions, policy results, approvals, settlements, documents.

Postgres (Akamai Managed PostgreSQL) when ``DATABASE_URL`` is set; a SQLite file otherwise
(``VOUCH_DATA_DIR/vouch.sqlite3``); ``sqlite://`` for in-memory tests. API state is loaded
from here at startup, so restarts are safe.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from ..models import PaymentRecord, Vendor

log = logging.getLogger(__name__)


def now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class Base(DeclarativeBase):
    pass


class PaymentRow(Base):
    __tablename__ = "payments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32))
    lifecycle: Mapped[str] = mapped_column(String(32))
    received_at: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class VendorRow(Base):
    __tablename__ = "vendors"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    data: Mapped[dict] = mapped_column(JSON)


class RunRow(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payment_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    llm_mode: Mapped[str] = mapped_column(String(16))
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    source: Mapped[str] = mapped_column(String(16), default="email")
    node_timings: Mapped[dict] = mapped_column(JSON, default=dict)
    trace: Mapped[dict] = mapped_column(JSON, default=dict)


class DecisionRow(Base):
    __tablename__ = "decisions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    payment_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32))
    risk: Mapped[str] = mapped_column(String(32))
    trust_score: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PolicyRow(Base):
    __tablename__ = "policy_results"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    payment_id: Mapped[str] = mapped_column(String(64), index=True)
    engine: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64))
    principal: Mapped[str] = mapped_column(String(32))
    allowed: Mapped[bool] = mapped_column(Boolean)
    reasons: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ApprovalRow(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payment_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(80), default="Owner")
    policy_rule: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SettlementRow(Base):
    __tablename__ = "settlements"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # batch id
    tx_id: Mapped[str] = mapped_column(String(80))
    payment_ids: Mapped[list] = mapped_column(JSON)
    total_cents: Mapped[int] = mapped_column(Integer)
    funding: Mapped[str] = mapped_column(String(16))
    scheduled_for: Mapped[str | None] = mapped_column(String(40), nullable=True)
    network: Mapped[str] = mapped_column(String(40), default="USDC · Base (simulated)")
    fee_cents: Mapped[int] = mapped_column(Integer, default=0)
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DocumentRow(Base):
    __tablename__ = "intake_documents"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payment_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    extractor: Mapped[str] = mapped_column(String(40))
    storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    text_excerpt: Mapped[str] = mapped_column(Text, default="")
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


class AuditStore:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine = make_engine(url)
        Base.metadata.create_all(self.engine)

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

    # ---- payments & vendors (API state) -----------------------------------
    def save_payment(self, p: PaymentRecord) -> None:
        with self.session() as s:
            row = s.get(PaymentRow, p.id)
            data = json.loads(p.model_dump_json(by_alias=True))
            if row is None:
                row = PaymentRow(
                    id=p.id,
                    vendor_id=p.vendor_id,
                    status=p.status,
                    lifecycle=p.lifecycle,
                    received_at=p.received_at,
                    data=data,
                )
                s.add(row)
            else:
                row.vendor_id, row.status, row.lifecycle, row.received_at, row.data = (
                    p.vendor_id,
                    p.status,
                    p.lifecycle,
                    p.received_at,
                    data,
                )
            s.commit()

    def load_payments(self) -> list[PaymentRecord]:
        with self.session() as s:
            rows = s.execute(select(PaymentRow).order_by(PaymentRow.received_at)).scalars().all()
            return [PaymentRecord.model_validate(r.data) for r in rows]

    def delete_all_payments(self) -> None:
        with self.session() as s:
            s.query(PaymentRow).delete()
            s.commit()

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

    # ---- audit trail ---------------------------------------------------------
    def start_run(self, llm_mode: str, model: str | None, source: str, payment_id: str | None = None) -> str:
        run_id = new_id("run")
        with self.session() as s:
            s.add(
                RunRow(
                    id=run_id,
                    payment_id=payment_id,
                    started_at=now(),
                    llm_mode=llm_mode,
                    model=model,
                    source=source,
                )
            )
            s.commit()
        return run_id

    def finish_run(
        self, run_id: str, payment_id: str | None, status: str, node_timings: dict, trace: dict
    ) -> None:
        with self.session() as s:
            row = s.get(RunRow, run_id)
            if row:
                row.finished_at, row.payment_id, row.status, row.node_timings, row.trace = (
                    now(),
                    payment_id,
                    status,
                    node_timings,
                    trace,
                )
                s.commit()

    def record_decision(self, run_id: str, p: PaymentRecord) -> None:
        with self.session() as s:
            s.add(
                DecisionRow(
                    id=new_id("dec"),
                    run_id=run_id,
                    payment_id=p.id,
                    status=p.status,
                    risk=p.risk,
                    trust_score=p.trust_score,
                    reason=p.reason,
                    evidence=[e.model_dump() for e in p.evidence],
                )
            )
            s.commit()

    def record_policy(
        self,
        run_id: str | None,
        payment_id: str,
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
                    payment_id=payment_id,
                    engine=engine,
                    principal=principal,
                    action=action,
                    allowed=allowed,
                    reasons=reasons,
                )
            )
            s.commit()

    def record_approval(
        self, payment_id: str, action: str, note: str, author: str, policy_rule: str | None
    ) -> str:
        aid = new_id("apr")
        with self.session() as s:
            s.add(
                ApprovalRow(
                    id=aid,
                    payment_id=payment_id,
                    action=action,
                    note=note,
                    author=author,
                    policy_rule=policy_rule,
                )
            )
            s.commit()
        return aid

    def has_owner_approval(self, payment_id: str) -> bool:
        with self.session() as s:
            row = s.execute(
                select(ApprovalRow).where(
                    ApprovalRow.payment_id == payment_id, ApprovalRow.action == "approve"
                )
            ).first()
            return row is not None

    def record_settlement(
        self,
        batch_id: str,
        tx_id: str,
        payment_ids: list[str],
        total_cents: int,
        funding: str,
        scheduled_for: str | None,
        fee_cents: int = 0,
    ) -> None:
        with self.session() as s:
            s.add(
                SettlementRow(
                    id=batch_id,
                    tx_id=tx_id,
                    payment_ids=payment_ids,
                    total_cents=total_cents,
                    funding=funding,
                    scheduled_for=scheduled_for,
                    fee_cents=fee_cents,
                )
            )
            s.commit()

    def last_settlement(self) -> dict | None:
        with self.session() as s:
            row = s.execute(select(SettlementRow).order_by(SettlementRow.settled_at.desc())).scalars().first()
            if not row:
                return None
            return {
                "batch_id": row.id,
                "tx_id": row.tx_id,
                "payment_ids": row.payment_ids,
                "total_cents": row.total_cents,
                "settled_at": row.settled_at.isoformat(),
            }

    def record_document(
        self,
        run_id: str | None,
        payment_id: str | None,
        filename: str,
        kind: str,
        sha256: str,
        extractor: str,
        text_excerpt: str,
        storage_key: str | None,
    ) -> None:
        with self.session() as s:
            s.add(
                DocumentRow(
                    id=new_id("doc"),
                    run_id=run_id,
                    payment_id=payment_id,
                    filename=filename,
                    kind=kind,
                    sha256=sha256,
                    extractor=extractor,
                    text_excerpt=text_excerpt[:4000],
                    storage_key=storage_key,
                )
            )
            s.commit()

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
                "payments": s.query(PaymentRow).count(),
                "vendors": s.query(VendorRow).count(),
                "runs": s.query(RunRow).count(),
                "decisions": s.query(DecisionRow).count(),
                "policy_results": s.query(PolicyRow).count(),
                "approvals": s.query(ApprovalRow).count(),
                "settlements": s.query(SettlementRow).count(),
                "documents": s.query(DocumentRow).count(),
                "embedding_cache": s.query(EmbeddingCacheRow).count(),
            }

    def audit_trail(self, payment_id: str) -> dict[str, Any]:
        with self.session() as s:
            runs = s.execute(select(RunRow).where(RunRow.payment_id == payment_id)).scalars().all()
            decisions = (
                s.execute(select(DecisionRow).where(DecisionRow.payment_id == payment_id)).scalars().all()
            )
            policies = s.execute(select(PolicyRow).where(PolicyRow.payment_id == payment_id)).scalars().all()
            approvals = (
                s.execute(select(ApprovalRow).where(ApprovalRow.payment_id == payment_id)).scalars().all()
            )
            docs = s.execute(select(DocumentRow).where(DocumentRow.payment_id == payment_id)).scalars().all()
            return {
                "runs": [
                    {
                        "id": r.id,
                        "llm_mode": r.llm_mode,
                        "model": r.model,
                        "status": r.status,
                        "started_at": r.started_at.isoformat(),
                        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                        "node_timings": r.node_timings,
                        "trace": r.trace,
                    }
                    for r in runs
                ],
                "decisions": [
                    {
                        "id": d.id,
                        "run_id": d.run_id,
                        "status": d.status,
                        "risk": d.risk,
                        "trust_score": d.trust_score,
                        "reason": d.reason,
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
                "documents": [
                    {
                        "filename": d.filename,
                        "kind": d.kind,
                        "sha256": d.sha256,
                        "extractor": d.extractor,
                        "storage_key": d.storage_key,
                    }
                    for d in docs
                ],
            }

    def reset(self) -> None:
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
