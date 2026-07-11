from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, Body, Path, Request, status
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.deps import AdminUser, UoWDep
from app.integrations.webhooks import verify_inbound
from app.schemas.webhooks import WebhookAck, WebhookDeliveryRequest, WebhookDeliveryResult
from app.workers.runtime import get_task_queue

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _extract_identity(
    provider: str,
    payload: dict[str, object],
    headers: Mapping[str, str],
    body: bytes,
) -> tuple[str, str]:
    """Derive a stable (external_id, event_type) for idempotency + routing."""

    if provider == "stripe":
        external_id = str(payload.get("id") or hashlib.sha256(body).hexdigest())
        return external_id, str(payload.get("type") or "unknown")
    if provider == "github":
        external_id = headers.get("X-GitHub-Delivery") or hashlib.sha256(body).hexdigest()
        return external_id, headers.get("X-GitHub-Event") or "unknown"

    external_id = (
        headers.get(get_settings().webhook_id_header)
        or str(payload.get("id") or "")
        or hashlib.sha256(body).hexdigest()
    )
    return external_id, str(payload.get("type") or payload.get("event") or "unknown")


@router.post(
    "/{provider}",
    response_model=WebhookAck,
    status_code=status.HTTP_200_OK,
    summary="Receive a signed webhook (verify, dedupe, store, enqueue)",
)
async def receive_webhook(
    provider: Annotated[str, Path(min_length=1, max_length=40)],
    request: Request,
    uow: UoWDep,
) -> WebhookAck:
    body = await request.body()
    # Verify signature over the raw bytes before trusting anything (raises InvalidSignature -> 400).
    verify_inbound(provider=provider, body=body, headers=request.headers)

    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {"value": payload}

    external_id, event_type = _extract_identity(provider, payload, request.headers, body)

    existing = await uow.webhooks.get_by_external_id(source=provider, external_id=external_id)
    if existing is not None:
        return WebhookAck(received=True, status="already_processed", event_id=existing.id)

    try:
        event = await uow.webhooks.record_event(
            source=provider,
            external_id=external_id,
            event_type=event_type,
            payload=payload,
        )
        await uow.commit()
    except IntegrityError:
        # Two provider retries can arrive concurrently. The unique index is the final arbiter;
        # after rollback, return the already stored event instead of surfacing a 500.
        await uow.rollback()
        existing = await uow.webhooks.get_by_external_id(
            source=provider,
            external_id=external_id,
        )
        if existing is None:
            raise
        return WebhookAck(received=True, status="already_processed", event_id=existing.id)

    # Respond fast; process asynchronously so a slow handler can't make the provider retransmit.
    queue = get_task_queue(request.app)
    await queue.enqueue("process_webhook_event", event_id=event.id)
    return WebhookAck(received=True, status="accepted", event_id=event.id)


@router.post(
    "/deliver/test",
    response_model=WebhookDeliveryResult,
    summary="Send a signed outbound webhook to a subscriber URL",
)
async def trigger_delivery(
    payload: Annotated[WebhookDeliveryRequest, Body()],
    current_user: AdminUser,
    request: Request,
) -> WebhookDeliveryResult:
    del current_user
    queue = get_task_queue(request.app)
    job_id = await queue.enqueue(
        "deliver_webhook",
        destination=payload.destination,
        event_type=payload.event_type,
        payload=payload.payload,
        provider=payload.provider,
    )
    record = queue.store.get(job_id)
    success = False
    status_code: int | None = None
    if record is not None and isinstance(record.result, dict):
        success = bool(record.result.get("success"))
        raw_status = record.result.get("status_code")
        status_code = int(raw_status) if isinstance(raw_status, int) else None
    return WebhookDeliveryResult(job_id=job_id, success=success, status_code=status_code)
