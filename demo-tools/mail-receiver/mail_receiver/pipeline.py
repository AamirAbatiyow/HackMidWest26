"""The ingest pipeline shared by the SMTP handler and the HTTP /inbound fallback."""

from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import UTC, datetime

from .config import Settings
from .delivery import DeliveryWorker
from .parse import ParsedMail, parse_message
from .state import ReceiverState
from .storage import DiskStore, ObjectStore

log = logging.getLogger(__name__)


def new_message_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f") + "-" + secrets.token_hex(3)


class Receiver:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = DiskStore(settings.data_dir)
        self.objects = ObjectStore(settings)
        self.state = ReceiverState(settings.recent_limit)
        self.state.seed_recent(self.store.recent_metas(settings.recent_limit))
        self.worker = DeliveryWorker(settings, self.store, self.state)

    async def start(self) -> None:
        await self.worker.start()

    async def stop(self) -> None:
        await self.worker.stop()

    def receiver_trace(self, msg_id: str, received_at: str, *, via: str, peer: str, helo: str) -> str:
        """A ``Received:``-style trace line describing *our* hop. Kept in meta.json only: the
        stored message and its existing Received/Authentication-Results headers stay untouched."""
        origin = helo or "unknown"
        if peer:
            origin += f" ({peer})"
        return f"from {origin} by {self.settings.hostname} via {via} id {msg_id}; {received_at}"

    def build_meta(self, msg_id: str, raw: bytes, parsed: ParsedMail, **envelope) -> dict:
        received_at = parsed.intake["received_at"]
        return {
            "id": msg_id,
            "received_at": received_at,
            "size": len(raw),
            **envelope,
            "receiver_trace": self.receiver_trace(
                msg_id,
                received_at,
                via=str(envelope.get("via", "")),
                peer=str(envelope.get("peer", "")),
                helo=str(envelope.get("helo", "")),
            ),
            "from": parsed.from_addr,
            "from_name": parsed.from_name,
            "reply_to": parsed.reply_to,
            "to": parsed.to,
            "subject": parsed.subject,
            "date": parsed.date,
            "message_id": parsed.message_id,
            "authentication_results": parsed.authentication_results,
            "received_headers": parsed.received,
            "attachments": [a.meta() for a in parsed.attachments],
            "attachments_kept": sum(1 for a in parsed.attachments if a.kept),
            "attachments_dropped": sum(1 for a in parsed.attachments if not a.kept),
            "body_text_chars": len(parsed.intake.get("body_text", "")),
            "body_html_chars": len(parsed.intake.get("body_html", "")),
            "warnings": parsed.warnings,
            "demo_marker": parsed.intake["headers"].get("X-Vouch-Demo", ""),
            "delivery": {"status": "received", "attempts": 0, "last_detail": ""},
        }

    async def ingest(
        self,
        raw: bytes,
        *,
        via: str,
        envelope_from: str = "",
        rcpt_tos: list[str] | None = None,
        peer: str = "",
        helo: str = "",
    ) -> str:
        """Store, parse and queue one message. Returns the receiver's message id."""
        msg_id = new_message_id()
        s = self.settings
        parsed = parse_message(
            raw,
            allowed_extensions=s.allowed_extensions,
            max_attachment_bytes=s.max_attachment_bytes,
            max_attachments=s.max_attachments,
        )
        meta = self.build_meta(
            msg_id,
            raw,
            parsed,
            via=via,
            envelope_from=envelope_from,
            rcpt_tos=rcpt_tos or [],
            peer=peer,
            helo=helo,
        )
        directory = self.store.save(msg_id, raw, parsed, meta)
        self.state.record_received(meta)
        log.info(
            "received %s via %s from=%s subject=%r attachments=%d kept/%d dropped size=%d",
            msg_id,
            via,
            parsed.from_addr,
            parsed.subject,
            meta["attachments_kept"],
            meta["attachments_dropped"],
            len(raw),
        )
        if self.objects.enabled:
            asyncio.create_task(self._mirror(msg_id, directory), name=f"mirror-{msg_id}")
        await self.worker.enqueue(msg_id)
        return msg_id

    async def _mirror(self, msg_id: str, directory) -> None:
        try:
            keys = await asyncio.to_thread(self.objects.upload_dir, msg_id, directory)
            self.store.update_meta(msg_id, object_keys=keys)
        except Exception as exc:  # the local copy is authoritative; mirroring is best effort
            log.warning("object storage mirror failed for %s: %s", msg_id, exc)
            self.store.update_meta(msg_id, object_storage_error=str(exc))

    # ---------------------------------------------------------------- views ----
    def health(self) -> dict:
        dead = self.store.dead_letter_count()
        status = "ok"
        if not self.settings.forwarding_enabled:
            status = "store-only"
        elif dead or (self.state.last_delivery and not self.state.last_delivery["ok"]):
            status = "degraded"
        return {
            "status": status,
            "uptime_s": self.state.uptime_s(),
            "counters_since": self.state.started_at.isoformat().replace("+00:00", "Z"),
            "queue_depth": self.worker.depth,
            "received_total": self.state.received_total,
            "rejected_recipients_total": self.state.rejected_rcpt_total,
            "delivered_total": self.state.delivered_total,
            "dead_letter_count": dead,
            "requeued_on_start": self.worker.requeued_on_start,
            "last_delivery": self.state.last_delivery,
            "config": self.settings.public_view(),
        }

    def recent(self) -> list[dict]:
        return list(self.state.recent)

    def message_view(self, msg_id: str) -> dict | None:
        """Metadata plus the forwarded IntakeRequest for one message, with attachment payloads
        elided (bytes never leave the disk store through this API)."""
        meta = self.store.load_meta(msg_id)
        if meta is None:
            return None
        try:
            intake = self.store.load_intake(msg_id)
        except (OSError, ValueError):
            intake = None
        if intake is not None:
            for att in intake.get("attachments", []):
                if "data_b64" in att:
                    att["data_b64"] = f"<{att.get('size', '?')} bytes elided>"
        return {"meta": meta, "intake": intake}
