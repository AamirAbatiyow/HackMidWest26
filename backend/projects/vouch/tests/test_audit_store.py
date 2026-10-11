"""Audit persistence: every run, decision, policy result, approval and settlement is written to the store,
and a fresh process restores the queue (restart-safe) and can still settle an approved card."""

from __future__ import annotations

import pytest

from vouch.audit import AuditStore
from vouch.domain import CardStatus
from vouch.service import VouchService


def _settings(settings, tmp_path):
    return settings.model_copy(update={"data_dir": tmp_path, "seed_demo": False})


def _service(settings, db_url: str, **kw) -> VouchService:
    return VouchService(settings, database_url=db_url, seed_demo=False, **kw)


def _by_vendor(svc: VouchService, prefix: str) -> dict:
    return next(p for p in svc.payments() if p["vendor"]["name"].startswith(prefix))


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{(tmp_path / 'audit.sqlite3').as_posix()}"


def test_store_opens_sqlite_fallback_when_postgres_unreachable(tmp_path):
    store = AuditStore.open(
        "postgresql+psycopg://nobody:x@127.0.0.1:1/vouch", f"sqlite:///{tmp_path}/fb.sqlite3"
    )
    assert store.backend == "sqlite"
    ok, _detail = store.ping()
    assert ok


def test_seed_writes_runs_cards_decisions_and_policy_rows(settings, tmp_path, db_url):
    svc = _service(_settings(settings, tmp_path), db_url)
    svc.seed(run_demo=True, background_vendors=30)
    counts = svc.store.counts()
    assert counts["runs"] == 1 and counts["payment_cards"] == 6
    assert counts["decisions"] >= 6, "one decision row per card at least"
    assert counts["vendors"] >= 30 + 6

    owner_actions = _by_vendor(svc, "Rheinland")
    svc.hold(owner_actions["id"], "check the discount", "Dana")
    svc.approve(owner_actions["id"], "fine", "Dana")
    counts = svc.store.counts()
    assert counts["approvals"] >= 1 and counts["policy_results"] >= 1
    trail = svc.store.audit_trail(owner_actions["id"])
    assert trail["decisions"] and trail["approvals"] and trail["policy_results"]
    assert any(a["action"] == "approve" for a in trail["approvals"])


def test_restart_restores_queue_and_can_still_settle(settings, tmp_path, db_url):
    first = _service(_settings(settings, tmp_path), db_url)
    first.seed(run_demo=True, background_vendors=30)
    rhein = _by_vendor(first, "Rheinland")
    bao = _by_vendor(first, "Bao Lin")
    first.approve(rhein["id"], "ok", "Dana")
    first.hold(bao["id"], "wait", "Dana")
    before = {p["id"]: (p["lifecycle"], p["status"], p["trust_score"]) for p in first.payments()}
    vendors_before = len(first.engine.vendors)

    # A new process: nothing in memory, everything comes back from the store.
    second = _service(_settings(settings, tmp_path), db_url)
    assert len(second.engine.vendors) == vendors_before
    after = {p["id"]: (p["lifecycle"], p["status"], p["trust_score"]) for p in second.payments()}
    assert after == before
    run, card = second.find(rhein["id"])
    assert run.graph is None and card.status == CardStatus.APPROVED

    receipt = second.settle([rhein["id"]], "now", "Dana", "after restart")
    assert receipt["tx_id"] and receipt["lines"][0]["tx_id"]
    assert second.payment(rhein["id"])["lifecycle"] == "settled"
    assert second.store.counts()["settlements"] == 1
    assert second.store.settlements()[0]["tx_id"] == receipt["tx_id"]

    # Third start: the settlement survived too and a held card is still held.
    third = _service(_settings(settings, tmp_path), db_url)
    assert third.payment(rhein["id"])["lifecycle"] == "settled"
    assert third.payment(rhein["id"])["settlement_tx_id"] == receipt["tx_id"]
    assert third.payment(bao["id"])["lifecycle"] == "held"


def test_interrupted_run_is_marked_failed_on_restore(settings, tmp_path, db_url):
    svc = _service(_settings(settings, tmp_path), db_url)
    run = svc.seed(run_demo=True, background_vendors=30)
    run.status = "running"
    svc.store.save_run(run)
    again = _service(_settings(settings, tmp_path), db_url)
    restored = again.engine.runs[run.id]
    assert restored.status == "failed" and "restart" in (restored.error or "")


def test_reset_clears_runs_but_keeps_vendors(settings, tmp_path, db_url):
    svc = _service(_settings(settings, tmp_path), db_url)
    svc.seed(run_demo=True, background_vendors=30)
    svc.reset(run_demo=False)
    counts = svc.store.counts()
    assert counts["runs"] == 0 and counts["payment_cards"] == 0
    assert counts["vendors"] >= 36 and svc.payments() == []


def test_opening_an_older_database_adds_the_columns_this_version_declares(db_url):
    """``create_all`` never alters existing tables: a store created before the per-document tool decision
    (``intake_documents.tool`` / ``fallback``), the strict-schema audit fields (``intake_decisions.
    reason_code`` / ``validation_errors``) and the P-09 send record (``kickback_drafts.sent_by`` /
    ``sent_via`` / ``message_id``) gains the columns on open, and the new rows write cleanly."""
    from sqlalchemy import create_engine, inspect, text

    old = create_engine(db_url)
    with old.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE kickback_drafts (card_id VARCHAR(64) PRIMARY KEY, run_id VARCHAR(64), "
                '"to" VARCHAR(255), subject VARCHAR(255), body TEXT, code VARCHAR(32), reason TEXT, '
                "missing_fields JSON, chosen_by VARCHAR(32), status VARCHAR(16), decided_by VARCHAR(80), "
                "decided_at DATETIME, note TEXT, sent_at DATETIME, created_at DATETIME)"
            )
        )
        conn.execute(
            text(
                'INSERT INTO kickback_drafts (card_id, "to", subject, body, code, status, created_at) '
                "VALUES ('run_0.1', 'ap@old.example', 'old', 'old body', 'unreadable_scan', 'approved', "
                "'2026-10-01 12:00:00')"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE intake_documents (id VARCHAR(64) PRIMARY KEY, run_id VARCHAR(64), "
                "card_id VARCHAR(64), filename VARCHAR(255), kind VARCHAR(16), sha256 VARCHAR(64), "
                "extractor VARCHAR(40), storage_key VARCHAR(255), text_excerpt TEXT, created_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO intake_documents (id, filename, kind, sha256, extractor, text_excerpt) "
                "VALUES ('doc_old', 'old.pdf', 'pdf', 'abc', 'pypdf+pdfplumber', '')"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE intake_decisions (id VARCHAR(64) PRIMARY KEY, run_id VARCHAR(64), "
                "card_id VARCHAR(64) NOT NULL, seq INTEGER, key VARCHAR(32), question TEXT, options JSON, "
                "answer VARCHAR(64), accepted BOOLEAN, engine VARCHAR(32), confidence FLOAT, latency_ms FLOAT, "
                "input_tokens INTEGER, output_tokens INTEGER, attempts INTEGER, error TEXT, note TEXT, "
                "created_at DATETIME)"
            )
        )
    old.dispose()
    store = AuditStore(db_url)
    columns = {c["name"] for c in inspect(store.engine).get_columns("intake_documents")}
    assert {"tool", "fallback"} <= columns
    decision_columns = {c["name"] for c in inspect(store.engine).get_columns("intake_decisions")}
    assert {"reason_code", "validation_errors"} <= decision_columns
    draft_columns = {c["name"] for c in inspect(store.engine).get_columns("kickback_drafts")}
    assert {"sent_by", "sent_via", "message_id"} <= draft_columns
    old_draft = store.kickback_drafts(status="approved")[0]
    assert old_draft["card_id"] == "run_0.1" and old_draft["sent_at"] is None
    assert (old_draft["sent_by"], old_draft["sent_via"], old_draft["message_id"]) == (None, None, None)
    store.record_document(
        "run_1", "run_1.1", "inv.xlsx", "xlsx", "def", "openpyxl", "Invoice", None,
        tool="excel_reader", fallback=None,
    )  # fmt: skip
    docs = store.audit_trail("run_1.1")["documents"]
    assert docs == [
        {
            "filename": "inv.xlsx",
            "kind": "xlsx",
            "sha256": "def",
            "extractor": "openpyxl",
            "tool": "excel_reader",
            "fallback": None,
            "storage_key": None,
        }
    ]
    assert store.counts()["documents"] == 2, "the pre-existing row is kept"
    # idempotent: a second open finds nothing to add
    AuditStore(db_url)
