from __future__ import annotations

from app.db.uow import SqlAlchemyUnitOfWork
from app.schemas.teams import TeamCreate, TeamRead


async def list_teams(*, uow: SqlAlchemyUnitOfWork) -> list[TeamRead]:
    teams = await uow.teams.list_all()
    return [TeamRead.model_validate(team) for team in teams]


async def create_team(*, uow: SqlAlchemyUnitOfWork, payload: TeamCreate) -> TeamRead:
    team = await uow.teams.create(name=payload.name)
    await uow.commit()
    return TeamRead.model_validate(team)
