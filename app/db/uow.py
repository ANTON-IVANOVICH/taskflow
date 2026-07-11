from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.outbox_repository import OutboxRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.team_repository import TeamRepository
from app.repositories.webhook_repository import WebhookRepository


class SqlAlchemyUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tasks = TaskRepository(session)
        self.teams = TeamRepository(session)
        self.outbox = OutboxRepository(session)
        self.payments = PaymentRepository(session)
        self.webhooks = WebhookRepository(session)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
