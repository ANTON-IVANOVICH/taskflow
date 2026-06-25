from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select, update

from app.db.models import OutboxEvent
from app.repositories.base import BaseRepository


class OutboxRepository(BaseRepository[OutboxEvent]):
    model = OutboxEvent

    async def add_event(self, *, topic: str, payload: dict[str, object]) -> OutboxEvent:
        event = OutboxEvent(topic=topic, payload=payload)
        self.session.add(event)
        await self.session.flush()
        return event

    async def list_unpublished(self, *, limit: int) -> list[OutboxEvent]:
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.id.asc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def mark_published(self, ids: Sequence[int]) -> None:
        if not ids:
            return
        await self.session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id.in_(ids))
            .values(published_at=datetime.now(UTC), attempts=OutboxEvent.attempts + 1)
        )

    async def count_unpublished(self) -> int:
        stmt = (
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
        )
        return await self.session.scalar(stmt) or 0
