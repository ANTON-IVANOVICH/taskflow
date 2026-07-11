from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models import WebhookDelivery, WebhookEvent
from app.repositories.base import BaseRepository


class WebhookRepository(BaseRepository[WebhookEvent]):
    model = WebhookEvent

    async def get_by_external_id(self, *, source: str, external_id: str) -> WebhookEvent | None:
        stmt = (
            select(WebhookEvent)
            .where(WebhookEvent.source == source, WebhookEvent.external_id == external_id)
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def record_event(
        self,
        *,
        source: str,
        external_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> WebhookEvent:
        event = WebhookEvent(
            source=source,
            external_id=external_id,
            event_type=event_type,
            payload=payload,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def mark_processed(self, event_id: int) -> None:
        event = await self.session.get(WebhookEvent, event_id)
        if event is not None:
            event.processed_at = datetime.now(UTC)
            await self.session.flush()

    async def record_delivery(
        self,
        *,
        destination: str,
        event_type: str,
        payload: dict[str, object],
        status_code: int | None,
        success: bool,
        attempts: int,
    ) -> WebhookDelivery:
        delivery = WebhookDelivery(
            destination=destination,
            event_type=event_type,
            payload=payload,
            status_code=status_code,
            success=success,
            attempts=attempts,
        )
        self.session.add(delivery)
        await self.session.flush()
        return delivery
