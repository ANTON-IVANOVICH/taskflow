from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class WebhookAck(BaseModel):
    received: bool = True
    status: str
    event_id: int | None = None


class WebhookDeliveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination: str = Field(min_length=1, max_length=500, pattern=r"^https?://")
    event_type: str = Field(min_length=1, max_length=80)
    payload: dict[str, object] = Field(default_factory=dict)
    provider: str = Field(default="generic", max_length=40)


class WebhookDeliveryResult(BaseModel):
    job_id: str
    success: bool
    status_code: int | None = None
