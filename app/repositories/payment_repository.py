from __future__ import annotations

from typing import cast

from sqlalchemy import select

from app.db.models import Payment
from app.repositories.base import BaseRepository


class PaymentRepository(BaseRepository[Payment]):
    model = Payment

    async def get_by_idempotency_key(self, *, provider: str, key: str) -> Payment | None:
        stmt = (
            select(Payment)
            .where(Payment.provider == provider, Payment.idempotency_key == key)
            .limit(1)
        )
        return cast(Payment | None, await self.session.scalar(stmt))

    async def get_by_external_id(self, *, provider: str, external_id: str) -> Payment | None:
        stmt = (
            select(Payment)
            .where(Payment.provider == provider, Payment.external_id == external_id)
            .limit(1)
        )
        return cast(Payment | None, await self.session.scalar(stmt))

    async def mark_status_by_external_id(
        self,
        *,
        provider: str,
        external_id: str,
        status: str,
    ) -> Payment | None:
        payment = await self.get_by_external_id(provider=provider, external_id=external_id)
        if payment is None:
            return None
        payment.status = status
        await self.session.flush()
        return payment
