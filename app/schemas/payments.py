from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CheckoutSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: int = Field(gt=0, le=10_000_000, description="Amount in the smallest currency unit")
    currency: str = Field(default="usd", min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    description: str = Field(min_length=1, max_length=500)
    success_url: str = Field(min_length=1, max_length=1000, pattern=r"^https?://")
    cancel_url: str = Field(min_length=1, max_length=1000, pattern=r"^https?://")
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=200)


class CheckoutSessionResponse(BaseModel):
    id: int
    provider: str
    external_id: str
    status: str
    checkout_url: str | None = None
    amount: int
    currency: str
    idempotency_key: str


class PaymentStatusResponse(BaseModel):
    id: int
    provider: str
    external_id: str | None
    status: str
    amount: int
    currency: str
    checkout_url: str | None = None
