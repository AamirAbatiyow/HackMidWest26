"""Forward parsed messages to the backend intake endpoint: queue, retry with exponential
backoff and jitter, dead-letter after the last attempt. Runs on the receiver's event loop."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from datetime import UTC, datetime

import aiohttp

from .config import Settings
from .storage import DiskStore

log = logging.getLogger(__name__)


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class DeliveryWorker:
    def __init__(self, settings: Settings, store: DiskStore, state) -> None:
        self.settings = settings
        self.store = store
        self.state = state
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.requeued_on_start = 0
        self._inflight = 0
        self._task: asyncio.Task | None = None
        self._session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------ lifecycle ----
    async def start(self) -> int:
        """Start the worker and re-queue deliveries left unfinished by a previous process.
        Returns how many were re-queued."""
        timeout = aiohttp.ClientTimeout(total=self.settings.delivery_timeout_s)
        self._session = aiohttp.ClientSession(timeout=timeout)
        requeued = 0
        if self.settings.forwarding_enabled:
            for msg_id in self.store.unfinished_ids(self.settings.requeue_scan_limit):
                await self.enqueue(msg_id)
                requeued += 1
            if requeued:
                log.info(
                    "re-queued %d unfinished deliver%s from disk", requeued, "y" if requeued == 1 else "ies"
                )
        self.requeued_on_start = requeued
        self._task = asyncio.create_task(self._run(), name="delivery-worker")
        return requeued

    async def stop(self) -> None:
        """Give in-flight forwards a bounded chance to finish, then cancel. Whatever is still
        queued or retrying is picked up again by :meth:`start` on the next run."""
        if self._task:
            drain = self.settings.shutdown_drain_s
            if drain > 0 and self.depth:
                log.info("draining %d queued forward(s) for up to %.0fs", self.depth, drain)
                try:
                    await asyncio.wait_for(self.queue.join(), timeout=drain)
                except TimeoutError:
                    log.warning("drain timed out; unfinished deliveries will be re-queued on restart")
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._session:
            await self._session.close()

    @property
    def depth(self) -> int:
        """Messages waiting or currently being forwarded (what /health reports as queue_depth)."""
        return self.queue.qsize() + self._inflight

    async def enqueue(self, msg_id: str) -> None:
        self.store.update_meta(msg_id, delivery={"status": "queued", "attempts": 0, "last_detail": ""})
        self.state.set_delivery(msg_id, status="queued", attempts=0, last_detail="")
        await self.queue.put(msg_id)

    async def requeue_dead_letters(self) -> int:
        n = 0
        for path in self.store.dead_letters():
            msg_id = path.stem
            self.store.remove_dead_letter(msg_id)
            await self.enqueue(msg_id)
            n += 1
        return n

    # ---------------------------------------------------------------- worker ----
    async def _run(self) -> None:
        while True:
            msg_id = await self.queue.get()
            self._inflight += 1
            try:
                await self.deliver_with_retries(msg_id)
            except Exception:  # pragma: no cover - defensive: the worker must never die
                log.exception("unexpected error delivering %s", msg_id)
            finally:
                self._inflight -= 1
                self.queue.task_done()

    def backoff(self, attempt: int) -> float:
        base = self.settings.delivery_backoff_base_s * (2 ** (attempt - 1))
        return min(base, self.settings.delivery_backoff_max_s) * random.uniform(0.8, 1.2)

    async def deliver_with_retries(self, msg_id: str) -> bool:
        if not self.settings.forwarding_enabled:
            detail = "BACKEND_INTAKE_URL not configured; stored only"
            self._record(msg_id, "stored", 0, detail, ok=None)
            return False
        if self.store.load_meta(msg_id) is None:
            log.error("cannot forward %s: its directory is gone from disk", msg_id)
            self.state.set_delivery(msg_id, status="missing", last_detail="message directory missing")
            return False
        attempts = 0
        while True:
            attempts += 1
            ok, detail = await self.post_once(msg_id)
            if ok:
                self._record(msg_id, "delivered", attempts, detail, ok=True)
                return True
            if attempts >= self.settings.delivery_max_attempts:
                self.store.write_dead_letter(msg_id, detail, attempts)
                self._record(msg_id, "dead_letter", attempts, detail, ok=False)
                log.error("dead-lettered %s after %d attempts: %s", msg_id, attempts, detail)
                return False
            delay = self.backoff(attempts)
            self._record(msg_id, "retrying", attempts, f"{detail}; retry in {delay:.1f}s", ok=False)
            log.warning(
                "delivery of %s failed (attempt %d): %s — retrying in %.1fs", msg_id, attempts, detail, delay
            )
            await asyncio.sleep(delay)

    async def post_once(self, msg_id: str) -> tuple[bool, str]:
        assert self._session is not None
        headers = {"X-Vouch-Receiver-Message-Id": msg_id, "User-Agent": "vouch-mail-receiver/0.1"}
        if self.settings.intake_shared_secret:
            headers[self.settings.intake_secret_header] = self.settings.intake_shared_secret
        meta = self.store.load_meta(msg_id) or {}
        if meta.get("envelope_from"):
            headers["X-Vouch-Envelope-From"] = str(meta["envelope_from"])
        try:
            if self.settings.backend_intake_format == "eml":
                # The backend's /v1/intake/eml is a multipart upload: field ``file`` + ``submitted_by``.
                form = aiohttp.FormData()
                form.add_field(
                    "file", self.store.load_raw(msg_id), filename="message.eml", content_type="message/rfc822"
                )
                form.add_field("submitted_by", self.settings.backend_submitted_by)
                resp_cm = self._session.post(self.settings.backend_intake_url, data=form, headers=headers)
            else:
                # /v1/intake takes the IntakeRequest JSON (headers, body_text, body_html, attachments).
                payload = self.store.load_intake(msg_id)
                payload.setdefault("submitted_by", self.settings.backend_submitted_by)
                resp_cm = self._session.post(self.settings.backend_intake_url, json=payload, headers=headers)
            async with resp_cm as resp:
                text = (await resp.text())[:300].replace("\n", " ")
                if 200 <= resp.status < 300:
                    return True, f"HTTP {resp.status} {text}".strip()
                return False, f"HTTP {resp.status} {text}".strip()
        except (TimeoutError, aiohttp.ClientError, OSError) as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def _record(self, msg_id: str, status: str, attempts: int, detail: str, *, ok: bool | None) -> None:
        delivery = {"status": status, "attempts": attempts, "last_detail": detail, "at": utcnow_iso()}
        self.store.update_meta(msg_id, delivery=delivery)
        self.state.set_delivery(msg_id, **delivery)
        if ok is not None and status in ("delivered", "dead_letter"):
            self.state.record_delivery_result(msg_id, ok, detail, attempts)
