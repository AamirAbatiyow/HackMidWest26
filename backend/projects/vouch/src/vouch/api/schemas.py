"""Request bodies. Responses are plain dicts shaped for the frontend's normalizers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..contracts import Attachment, IntakeRequest, Source


class ActionBody(BaseModel):
    note: str | None = None
    author: str = "Owner"


class SettleBody(BaseModel):
    payment_ids: list[str] = Field(min_length=1)
    funding: Literal["now", "scheduled"] = "now"


class IntakeJsonBody(BaseModel):
    """JSON intake. Either pass raw ``headers`` or the convenience fields below (both work)."""

    headers: dict[str, str] = Field(default_factory=dict)
    from_addr: str | None = Field(default=None, alias="from")
    reply_to: str | None = None
    to: str | None = None
    subject: str | None = None
    authentication_results: str | list[str] | None = None
    body_text: str = ""
    body_html: str = ""
    attachments: list[Attachment] = Field(default_factory=list)
    source: Source = "email"

    model_config = {"populate_by_name": True}

    def to_request(self) -> IntakeRequest:
        headers = dict(self.headers)
        if self.from_addr:
            headers.setdefault("From", self.from_addr)
        if self.reply_to:
            headers.setdefault("Reply-To", self.reply_to)
        if self.to:
            headers.setdefault("To", self.to)
        if self.subject:
            headers.setdefault("Subject", self.subject)
        if self.authentication_results:
            ar = self.authentication_results
            headers.setdefault("Authentication-Results", ar if isinstance(ar, str) else "\n".join(ar))
        return IntakeRequest(
            headers=headers,
            body_text=self.body_text,
            body_html=self.body_html,
            attachments=self.attachments,
            source=self.source,
        )


class VendorResolveBody(BaseModel):
    name: str | None = None
    email: str | None = None
    tax_id: str | None = None
    bank_account: str | None = None
    address: str | None = None
    phone: str | None = None


class SenderCheckBody(BaseModel):
    headers: dict[str, str] = Field(default_factory=dict)
    claimed_vendor_id: str | None = None


class RedTeamRunBody(BaseModel):
    live: bool = False
