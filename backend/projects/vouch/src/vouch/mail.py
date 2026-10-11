"""Outbound mail for approved kickback drafts.

This is the only place a reply to a sender can leave the service, and it is reached through one path:
``VouchService.kickback_send`` after Cedar P-09 (owner principal, the owner's P-08 approval on record, not
sent before, payment not settled). No node, hook, model or background job calls a ``Mailer``.

``OutboxMailer`` (the default) delivers nothing: it stamps a local message id so the console can show the
hand-off and keeps the message in memory. A real integration implements ``Mailer`` and is injected with
``VouchService(mailer=...)``.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Any, Protocol


class Mailer(Protocol):
    name: str

    def send(self, to: str, subject: str, body: str, *, reply_to: str | None = None) -> str:
        """Deliver one message; returns the message id the audit record keeps."""
        ...


@dataclass
class OutboxMailer:
    """Default: records the hand-off, sends nothing."""

    name: str = "outbox"
    sent: list[dict[str, Any]] = field(default_factory=list)

    def send(self, to: str, subject: str, body: str, *, reply_to: str | None = None) -> str:
        message_id = f"outbox-{secrets.token_hex(6)}"
        self.sent.append(
            {"message_id": message_id, "to": to, "subject": subject, "body": body, "reply_to": reply_to}
        )
        return message_id


__all__ = ["Mailer", "OutboxMailer"]
