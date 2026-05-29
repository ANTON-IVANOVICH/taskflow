from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import Task, TaskEvent, Team
from app.db.session import async_session_maker, engine

_schema_ready = False
_schema_lock = asyncio.Lock()


async def init_schema_and_seed() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    if not get_settings().db_seed_enabled:
        return

    async with async_session_maker() as session:
        teams_count = await session.scalar(select(func.count()).select_from(Team))
        if (teams_count or 0) > 0:
            return

        team_platform = Team(name="Platform")
        team_product = Team(name="Product")
        session.add_all([team_platform, team_product])
        await session.flush()

        task1 = Task(
            team_id=team_platform.id,
            title="Prepare onboarding checklist",
            description="Finalize docs for new team members",
            priority=3,
            status="in_progress",
            assignee="alice@taskflow.dev",
            tags=["hr", "onboarding"],
        )
        task2 = Task(
            team_id=team_platform.id,
            title="Fix production incident",
            description="Investigate elevated latency in API",
            priority=5,
            status="blocked",
            assignee="bob@taskflow.dev",
            tags=["incident", "backend"],
        )
        session.add_all([task1, task2])
        await session.flush()

        now = datetime.now(UTC)
        session.add_all(
            [
                TaskEvent(
                    task_id=task1.id,
                    event_type="task_created",
                    payload={"source": "seed", "title": task1.title},
                    occurred_at=now,
                ),
                TaskEvent(
                    task_id=task2.id,
                    event_type="task_created",
                    payload={"source": "seed", "title": task2.title},
                    occurred_at=now,
                ),
            ]
        )
        await session.commit()


async def ensure_schema_initialized() -> None:
    global _schema_ready
    if _schema_ready:
        return
    async with _schema_lock:
        if _schema_ready:
            return
        await init_schema_and_seed()
        _schema_ready = True
