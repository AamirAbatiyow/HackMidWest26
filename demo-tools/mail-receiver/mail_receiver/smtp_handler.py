"""aiosmtpd handler: recipient policy, then hand the raw message to the pipeline."""

from __future__ import annotations

import asyncio
import logging

from aiosmtpd.smtp import SMTP, Envelope, Session

from .config import Settings
from .pipeline import Receiver

log = logging.getLogger(__name__)


class VouchHandler:
    def __init__(self, receiver: Receiver, port: int) -> None:
        self.receiver = receiver
        self.port = port

    @property
    def settings(self) -> Settings:
        return self.receiver.settings

    async def handle_RCPT(
        self, server: SMTP, session: Session, envelope: Envelope, address: str, rcpt_options: list[str]
    ) -> str:
        if not self.settings.accepts(address):
            self.receiver.state.record_rejected_rcpt()
            log.info("rejected RCPT TO %s from peer %s", address, session.peer)
            return "550 5.1.1 Mailbox unavailable"
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server: SMTP, session: Session, envelope: Envelope) -> str:
        raw = envelope.original_content or b""
        if not raw.strip():
            return "554 5.6.0 Empty message"
        peer = f"{session.peer[0]}:{session.peer[1]}" if session.peer else ""
        msg_id = await self.receiver.ingest(
            raw,
            via=f"smtp:{self.port}",
            envelope_from=envelope.mail_from or "",
            rcpt_tos=list(envelope.rcpt_tos),
            peer=peer,
            helo=session.host_name or "",
        )
        return f"250 OK: queued as {msg_id}"


def smtp_factory(receiver: Receiver, port: int):
    """Factory for ``loop.create_server``: one SMTP protocol instance per connection."""
    settings = receiver.settings
    handler = VouchHandler(receiver, port)

    def factory() -> SMTP:
        return SMTP(
            handler,
            data_size_limit=settings.max_message_bytes,
            enable_SMTPUTF8=True,
            hostname=settings.hostname,
            ident="Vouch mail receiver",
            timeout=120,
        )

    return factory


async def start_smtp_servers(receiver: Receiver) -> list[asyncio.AbstractServer]:
    loop = asyncio.get_running_loop()
    servers: list[asyncio.AbstractServer] = []
    for port in receiver.settings.smtp_ports:
        try:
            server = await loop.create_server(smtp_factory(receiver, port), receiver.settings.smtp_host, port)
        except PermissionError:
            log.error("cannot bind SMTP port %d (needs root or CAP_NET_BIND_SERVICE); skipping", port)
            continue
        except OSError as exc:
            log.error("cannot bind SMTP port %d: %s; skipping", port, exc)
            continue
        servers.append(server)
        log.info(
            "SMTP listening on %s:%d as %s", receiver.settings.smtp_host, port, receiver.settings.hostname
        )
    if not servers:
        raise SystemExit("no SMTP port could be bound")
    return servers
