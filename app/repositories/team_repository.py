from __future__ import annotations

from sqlalchemy import select

from app.db.models import Team
from app.repositories.base import BaseRepository


class TeamRepository(BaseRepository[Team]):
    model = Team

    async def list_all(self) -> list[Team]:
        stmt = select(Team).order_by(Team.id.asc())
        return list((await self.session.scalars(stmt)).all())

    async def get_by_name(self, name: str) -> Team | None:
        stmt = select(Team).where(Team.name == name)
        return await self.session.scalar(stmt)
