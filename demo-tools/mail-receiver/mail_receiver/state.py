"""In-memory view for /health and /recent (metadata only; bodies and attachments stay on disk)."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime


class ReceiverState:
    def __init__(self, recent_limit: int = 20) -> None:
        self.started_at = datetime.now(UTC)
        self.received_total = 0
        self.rejected_rcpt_total = 0
        self.delivered_total = 0
        self.dead_letter_total = 0
        self.last_delivery: dict | None = None
        self.recent: deque[dict] = deque(maxlen=recent_limit)

    def uptime_s(self) -> int:
        return int((datetime.now(UTC) - self.started_at).total_seconds())

    def record_received(self, meta: dict) -> None:
        self.received_total += 1
        self.recent.appendleft(meta)

    def record_rejected_rcpt(self) -> None:
        self.rejected_rcpt_total += 1

    def set_delivery(self, msg_id: str, **delivery) -> None:
        for meta in self.recent:
            if meta.get("id") == msg_id:
                meta["delivery"] = {**meta.get("delivery", {}), **delivery}
                break

    def record_delivery_result(self, msg_id: str, ok: bool, detail: str, attempts: int) -> None:
        if ok:
            self.delivered_total += 1
        else:
            self.dead_letter_total += 1
        self.last_delivery = {
            "at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "message_id": msg_id,
            "ok": ok,
            "attempts": attempts,
            "detail": detail,
        }

    def seed_recent(self, metas: list[dict]) -> None:
        """Restore the recent list from disk on startup (newest first)."""
        for meta in reversed(metas):
            self.recent.appendleft(meta)
