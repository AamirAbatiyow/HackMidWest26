"""VouchService: the one object the API, CLI and tests share. Owns the store, the vendor
directory, the LLM runtime, the pipeline and the in-memory view of payments (write-through
to the audit store, reloaded on startup)."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta

from .audit import AuditStore, new_id
from .config import LlmMode, Settings, get_settings
from .graph import Services, VouchPipeline
from .llm import LlmRuntime
from .models import AuditNote, IntakeRequest, PaymentRecord, iso, utcnow
from .policy import PaymentAttrs, authorize
from .storage import AttachmentStore
from .vendors import VendorDirectory, index_vendors, make_embedding_index

log = logging.getLogger(__name__)


class PolicyDenied(Exception):
    def __init__(self, action: str, reasons: list[str]) -> None:
        super().__init__(f"{action} denied by policy: {', '.join(reasons)}")
        self.action = action
        self.reasons = reasons


class NotFound(Exception):
    pass


class VouchService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        llm_mode: LlmMode | None = None,
        database_url: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        url = database_url or self.settings.effective_database_url
        self.store = AuditStore(url)
        self.llm = LlmRuntime(
            self.settings,
            mode=llm_mode,
            embedding_lookup=self.store.embedding_lookup,
            embedding_persist=self.store.embedding_persist,
        )
        self.directory = VendorDirectory(self.store.load_vendors())
        self.embedding_index = make_embedding_index(self.store.engine, url.startswith("postgresql"))
        self.attachments = AttachmentStore(self.settings)
        self.pipeline = VouchPipeline(
            Services(
                settings=self.settings,
                llm=self.llm,
                directory=self.directory,
                embedding_index=self.embedding_index,
                store=self.store,
                attachments=self.attachments,
            )
        )
        self.payments: dict[str, PaymentRecord] = {p.id: p for p in self.store.load_payments()}
        self.started_at = utcnow()
        self.vendors_indexed = 0

    # ------------------------------------------------------------ vendors ----
    def load_vendors(self, vendors) -> None:
        for v in vendors:
            self.directory.add(v)
        self.store.save_vendors(list(vendors))

    def index_vendor_embeddings(self) -> int:
        self.vendors_indexed = index_vendors(
            self.directory, self.llm.embedder_or_none(), self.embedding_index
        )
        return self.vendors_indexed

    # ------------------------------------------------------------- intake ----
    async def intake(
        self, request: IntakeRequest, *, received_at: datetime | None = None, payment_id: str | None = None
    ) -> PaymentRecord:
        existing = sorted(self.payments.values(), key=lambda p: p.received_at)
        record, _ctx = await self.pipeline.run_intake(
            request, existing=existing, payment_id=payment_id, received_at=received_at
        )
        self.payments[record.id] = record
        self._link_relations(record)
        return record

    def _link_relations(self, record: PaymentRecord) -> None:
        """Make duplicate/split links visible from both sides."""
        if record.duplicate_of and record.duplicate_of in self.payments:
            pass  # the earlier copy stays as-is: it is the one that is ready to pay
        if record.split_with and record.split_with in self.payments:
            other = self.payments[record.split_with]
            if other.split_with is None and other.lifecycle == "pending":
                other.split_with = record.id
                if other.risk == "none":
                    other.risk = "duplicate_or_split"
                if other.status == "vouched":
                    other.status = "quick_check"
                    other.reason = f"One of two invoices just under your approval limit, sent minutes apart ({record.invoice_number} followed)."
                    other.checklist = record.checklist
                    other.fast_pay_eligible = False
                    other.evidence = [e for e in other.evidence] + [
                        e.model_copy(update={"id": f"x{i}"})
                        for i, e in enumerate(record.evidence)
                        if e.direction == "concern"
                    ]
                other.updated_at = iso(utcnow()) or ""
                self.store.save_payment(other)

    # ------------------------------------------------------------- owner actions ----
    def get(self, payment_id: str) -> PaymentRecord:
        p = self.payments.get(payment_id)
        if p is None:
            raise NotFound(payment_id)
        return p

    def list(self) -> list[PaymentRecord]:
        return sorted(self.payments.values(), key=lambda p: p.received_at)

    def _attrs(self, p: PaymentRecord) -> PaymentAttrs:
        return PaymentAttrs(
            status=p.status,
            lifecycle=p.lifecycle,
            risk=p.risk,
            trust_score=p.trust_score,
            fast_pay_eligible=p.fast_pay_eligible,
            bank_changed=bool(p.bank_change and p.bank_change.changed),
            bank_change_verified=bool(p.bank_change and p.bank_change.requester_verified),
            amount_cents=p.amount_cents,
            vendor_known=bool(p.vendor_resolution and p.vendor_resolution.status == "known"),
        )

    def _owner_action(
        self, payment_id: str, action: str, note: str | None, author: str, default_note: str
    ) -> PaymentRecord:
        p = self.get(payment_id)
        outcome = authorize("Owner", action, self._attrs(p), payment_id=p.id)
        self.store.record_policy(
            p.run_id, p.id, outcome.engine, "owner", action, outcome.allowed, outcome.reasons
        )
        if not outcome.allowed:
            raise PolicyDenied(action, outcome.reasons)
        text = (note or "").strip() or default_note
        p.audit_notes.insert(0, AuditNote(id=new_id("n"), at=iso(utcnow()) or "", text=text, author=author))
        if action == "approve":
            p.lifecycle = "approved"
            p.status = "vouched"
        elif action == "hold":
            p.lifecycle = "held"
        elif action == "appeal":
            p.lifecycle = "appealed"
            p.status = "vouched"
            p.trust_score = max(p.trust_score, 70)
        p.updated_at = iso(utcnow()) or ""
        self.store.record_approval(
            p.id, action, text, author, outcome.reasons[0] if outcome.reasons else None
        )
        self.store.save_payment(p)
        return p

    def approve(self, payment_id: str, note: str | None = None, author: str = "Owner") -> PaymentRecord:
        return self._owner_action(payment_id, "approve", note, author, "Marked as verified by owner.")

    def hold(self, payment_id: str, note: str | None = None, author: str = "Owner") -> PaymentRecord:
        return self._owner_action(payment_id, "hold", note, author, "Held for a quick check.")

    def appeal(self, payment_id: str, note: str | None = None, author: str = "Owner") -> PaymentRecord:
        return self._owner_action(payment_id, "appeal", note, author, "Owner vouched for this vendor.")

    def settle(self, payment_ids: list[str], funding: str = "now") -> dict:
        """Simulated stablecoin settlement: policy-checked per payment, recorded with a tx id.

        The XRPL/USDC adapter from the original backend is not present in this tree; this
        produces a deterministic receipt so the owner flow is complete end to end.
        """
        items = [self.get(pid) for pid in payment_ids]
        for p in items:
            if p.lifecycle == "pending" and p.status == "vouched":
                # An approve click in the UI always precedes settle; accept implicit approval
                # for vouched rows but record it so the audit trail shows who approved.
                self.approve(p.id, "Approved in batch", "Owner")
            outcome = authorize(
                "System",
                "settle",
                self._attrs(p),
                {"owner_approval_recorded": self.store.has_owner_approval(p.id)},
                payment_id=p.id,
            )
            self.store.record_policy(
                p.run_id, p.id, outcome.engine, "system", "settle", outcome.allowed, outcome.reasons
            )
            if not outcome.allowed:
                raise PolicyDenied(
                    "settle", outcome.reasons + [f"payment {p.id} is {p.lifecycle}/{p.status}"]
                )
        batch_id = f"batch-{secrets.token_hex(3)}"
        tx_id = "0x" + secrets.token_hex(32)
        settled_at = utcnow()
        scheduled_for = None
        if funding == "scheduled":
            nxt = (settled_at + timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
            scheduled_for = iso(nxt)
        total = sum(p.amount_cents for p in items)
        for p in items:
            p.lifecycle = "settled"
            p.settlement_tx_id = tx_id
            p.batch_id = batch_id
            p.updated_at = iso(settled_at) or ""
            self.store.save_payment(p)
        self.store.record_settlement(batch_id, tx_id, [p.id for p in items], total, funding, scheduled_for)
        return {
            "batch_id": batch_id,
            "tx_id": tx_id,
            "explorer_url": f"https://explorer.vouch.example/tx/{tx_id}",
            "settled_at": iso(settled_at),
            "funding": funding,
            "scheduled_for": scheduled_for,
            "total_amount": total / 100,
            "total_cents": total,
            "lines": [
                {
                    "payment_id": p.id,
                    "vendor_name": p.vendor_name,
                    "invoice_number": p.invoice_number,
                    "amount": p.amount_cents / 100,
                }
                for p in items
            ],
            "network": "USDC · Base (simulated)",
            "fee_usd": 0,
        }

    # ------------------------------------------------------------- admin ----
    def reset_payments(self) -> None:
        self.payments.clear()
        self.store.delete_all_payments()

    def discard(self, payment_id: str) -> None:
        """Remove a payment from the queue (memory + store) but keep its audit rows."""
        self.payments.pop(payment_id, None)
        self.store.delete_payment(payment_id)

    def vendors(self) -> list:
        return self.directory.all()

    def uptime_s(self) -> int:
        return int((utcnow() - self.started_at).total_seconds())

    @staticmethod
    def now() -> datetime:
        return datetime.now(UTC)
