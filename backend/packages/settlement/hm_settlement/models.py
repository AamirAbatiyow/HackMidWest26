from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PaymentStatus(StrEnum):
    PENDING = "pending"
    HELD = "held"  # escrowed / conditional, awaiting release
    SETTLED = "settled"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PaymentRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    currency: str = "USD"  # adapter maps to XRP / IOU / USDC
    destination: str  # chain address or internal payee id
    memo: str | None = None
    idempotency_key: str  # same key -> same receipt, never a double payment
    metadata: dict[str, Any] = Field(default_factory=dict)


class Quote(BaseModel):
    amount: Decimal
    currency: str
    network_fee: Decimal = Decimal("0")
    network: str
    expires_at: datetime | None = None


class PaymentReceipt(BaseModel):
    tx_id: str
    status: PaymentStatus
    network: str
    amount: Decimal
    currency: str
    destination: str
    idempotency_key: str
    explorer_url: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw: dict[str, Any] = Field(default_factory=dict)
