"""Background job handlers.

Each handler takes a :class:`JobContext` first, then keyword arguments. They are designed to
run identically under the in-process eager queue and under an ARQ worker process, so they own
their own DB session and never assume a request-scoped one.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.core.concurrency import run_cpu_bound
from app.core.config import get_settings
from app.db.bootstrap import ensure_schema_initialized
from app.db.models import OutboxEvent
from app.db.session import async_session_maker
from app.db.uow import SqlAlchemyUnitOfWork
from app.integrations.runtime import default_email_service, default_resilient_client
from app.integrations.webhooks import build_delivery_headers, get_webhook_secret
from app.workers.queue import JobContext, JobHandler

logger = logging.getLogger("taskflow.workers")


def _build_report_digest(rows: list[tuple[str, int, list[str]]]) -> dict[str, object]:
    """Pure CPU work: aggregate task rows into a report summary + stable fingerprint."""

    status_counter: Counter[str] = Counter()
    priority_counter: Counter[int] = Counter()
    tag_counter: Counter[str] = Counter()
    for status, priority, tags in rows:
        status_counter[status] += 1
        priority_counter[priority] += 1
        for tag in tags:
            tag_counter[tag] += 1

    summary: dict[str, object] = {
        "total": len(rows),
        "by_status": dict(sorted(status_counter.items())),
        "by_priority": {str(k): v for k, v in sorted(priority_counter.items())},
        "top_tags": [tag for tag, _ in tag_counter.most_common(5)],
    }
    fingerprint = hashlib.sha256(
        json.dumps(summary, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    summary["fingerprint"] = fingerprint
    return summary


async def generate_report(
    ctx: JobContext, *, team_id: int, report_format: str = "summary"
) -> dict[str, object]:
    """Build an aggregate report for a team; offloads the aggregation to a worker thread."""

    await ensure_schema_initialized()
    await ctx.report(1, 3, "loading tasks")
    async with async_session_maker() as session:
        uow = SqlAlchemyUnitOfWork(session)
        tasks = await uow.tasks.filter_tasks(team_id=team_id)

    await ctx.report(2, 3, "aggregating")
    rows = [(task.status, task.priority, list(task.tags)) for task in tasks]
    summary = await run_cpu_bound(_build_report_digest, rows)

    await ctx.report(3, 3, "report ready")
    return {
        "team_id": team_id,
        "format": report_format,
        "generated_at": datetime.now(UTC).isoformat(),
        **summary,
    }


async def relay_outbox(ctx: JobContext, *, batch_size: int = 100) -> dict[str, object]:
    """Publish unpublished outbox events to the real-time broker and mark them delivered.

    The read, publish and mark-published run in one transaction so a crash mid-relay simply
    re-publishes (at-least-once) rather than dropping events.
    """

    await ensure_schema_initialized()
    published = 0
    async with async_session_maker() as session:
        uow = SqlAlchemyUnitOfWork(session)
        events = await uow.outbox.list_unpublished(limit=batch_size)
        for event in events:
            if ctx.broker is not None:
                try:
                    await ctx.broker.publish(event.topic, event.payload)
                except Exception:  # noqa: BLE001 - broker hiccup must not block the relay
                    logger.warning("outbox_publish_failed", extra={"topic": event.topic})
            published += 1
        await uow.outbox.mark_published([event.id for event in events])
        await uow.commit()
    if published:
        await ctx.report(1, 1, f"relayed {published} events")
    return {"published": published}


async def purge_published_outbox(
    ctx: JobContext, *, older_than_hours: int = 24
) -> dict[str, object]:
    """Periodic cleanup: delete delivered outbox rows older than the retention window."""

    await ensure_schema_initialized()
    cutoff = datetime.now(UTC) - timedelta(hours=older_than_hours)
    async with async_session_maker() as session:
        result = await session.execute(
            delete(OutboxEvent).where(
                OutboxEvent.published_at.is_not(None),
                OutboxEvent.published_at < cutoff,
            )
        )
        await session.commit()
    deleted: int = getattr(result, "rowcount", 0) or 0
    await ctx.report(1, 1, f"purged {deleted} delivered events")
    return {"deleted": deleted}


async def send_welcome_email(ctx: JobContext, *, email: str, name: str) -> dict[str, object]:
    """Send a welcome email, or explicitly report a local offline skip."""

    result = await default_email_service.send(
        to=email,
        subject="Welcome to TaskFlow",
        text=f"Hi {name}, welcome to TaskFlow.",
        html=f"<p>Hi {name}, welcome to TaskFlow.</p>",
        idempotency_key=f"welcome:{email}",
    )
    logger.info(
        "welcome_email_processed",
        extra={"email": email, "name": name, "status": result.status},
    )
    return {
        "status": result.status,
        "provider": result.provider,
        "message_id": result.message_id,
        "to": email,
    }


async def process_webhook_event(ctx: JobContext, *, event_id: int) -> dict[str, object]:
    """Process a stored webhook and apply known payment state transitions."""

    await ensure_schema_initialized()
    async with async_session_maker() as session:
        uow = SqlAlchemyUnitOfWork(session)
        event = await uow.webhooks.get(event_id)
        if event is None:
            return {"event_id": event_id, "processed": False, "reason": "not_found"}
        if event.processed_at is not None:
            return {"event_id": event_id, "processed": True, "duplicate": True}

        payment_status = _payment_status_from_webhook(event.source, event.event_type)
        payment_external_id = _payment_external_id(event.payload)
        if payment_status is not None and payment_external_id is not None:
            await uow.payments.mark_status_by_external_id(
                provider=event.source,
                external_id=payment_external_id,
                status=payment_status,
            )
        await uow.webhooks.mark_processed(event_id)
        await uow.commit()
    await ctx.report(1, 1, f"processed webhook {event_id}")
    return {
        "event_id": event_id,
        "processed": True,
        "payment_status": payment_status,
    }


def _payment_status_from_webhook(source: str, event_type: str) -> str | None:
    if source != "stripe":
        return None
    return {
        "checkout.session.completed": "paid",
        "payment_intent.succeeded": "paid",
        "checkout.session.expired": "expired",
        "payment_intent.payment_failed": "failed",
        "charge.refunded": "refunded",
    }.get(event_type)


def _payment_external_id(payload: dict[str, object]) -> str | None:
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    obj = data.get("object")
    if not isinstance(obj, dict):
        return None
    external_id = obj.get("id")
    return external_id if isinstance(external_id, str) else None


async def deliver_webhook(
    ctx: JobContext,
    *,
    destination: str,
    event_type: str,
    payload: dict[str, object],
    provider: str = "generic",
) -> dict[str, object]:
    """Sign and POST an outbound webhook via the resilient client, then record the delivery."""

    secret = get_webhook_secret(provider)
    settings = get_settings()
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    headers = build_delivery_headers(secret, body, event_type)

    status_code: int | None = None
    success = False
    try:
        response = await default_resilient_client.request(
            "POST",
            destination,
            content=body,
            headers=headers,
            breaker_name=f"webhook:{destination}",
            timeout=settings.webhook_delivery_timeout,
        )
        status_code = response.status_code
        success = 200 <= response.status_code < 300
    except Exception:  # noqa: BLE001 - delivery failure must be recorded, not raised
        logger.warning("webhook_delivery_failed", extra={"destination": destination})

    await ensure_schema_initialized()
    async with async_session_maker() as session:
        uow = SqlAlchemyUnitOfWork(session)
        await uow.webhooks.record_delivery(
            destination=destination,
            event_type=event_type,
            payload=payload,
            status_code=status_code,
            success=success,
            attempts=1,
        )
        await uow.commit()
    await ctx.report(1, 1, f"delivered to {destination}: {status_code}")
    return {"success": success, "status_code": status_code}


JOB_HANDLERS: dict[str, JobHandler] = {
    "generate_report": generate_report,
    "relay_outbox": relay_outbox,
    "purge_published_outbox": purge_published_outbox,
    "send_welcome_email": send_welcome_email,
    "process_webhook_event": process_webhook_event,
    "deliver_webhook": deliver_webhook,
}
