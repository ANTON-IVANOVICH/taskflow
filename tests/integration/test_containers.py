from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.models import Team
from app.repositories.task_repository import TaskRepository
from tests.factories import TaskCreateFactory

pytestmark = [pytest.mark.integration, pytest.mark.slow]

ROOT = Path(__file__).resolve().parents[2]


def _containers_enabled() -> None:
    if os.getenv("RUN_CONTAINERS") != "1":
        pytest.skip("set RUN_CONTAINERS=1 to run Docker-backed integration tests")


@pytest.fixture(scope="session")
def postgres_container():
    _containers_enabled()
    postgres_module = pytest.importorskip("testcontainers.postgres")
    with postgres_module.PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def redis_container():
    _containers_enabled()
    redis_module = pytest.importorskip("testcontainers.redis")
    with redis_module.RedisContainer("redis:7-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def postgres_dsn(postgres_container) -> str:
    return postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://",
        "postgresql+asyncpg://",
    )


@pytest.fixture(scope="session")
def migrated_postgres(postgres_dsn: str) -> str:
    env = os.environ.copy()
    env["DATABASE_URL"] = postgres_dsn
    env["POSTGRES_DSN"] = postgres_dsn
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), "upgrade", "head"],
        cwd=ROOT,
        env=env,
        check=True,
    )
    return postgres_dsn


@pytest_asyncio.fixture
async def postgres_session(migrated_postgres: str):
    engine = create_async_engine(migrated_postgres, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_container_accepts_asyncpg_connection(postgres_container) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    dsn = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://",
        "postgresql://",
    )
    connection = await asyncpg.connect(dsn)
    try:
        result = await connection.fetchval("SELECT 1")
    finally:
        await connection.close()
    assert result == 1


@pytest.mark.asyncio
async def test_postgres_migrations_create_schema(migrated_postgres: str) -> None:
    engine = create_async_engine(migrated_postgres, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            version = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            table_names = set(
                await connection.scalars(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
            )
    finally:
        await engine.dispose()

    assert version == "20260711_0004"
    assert {"teams", "tasks", "outbox_events", "webhook_events", "payments"} <= table_names


@pytest.mark.asyncio
async def test_task_repository_filters_rows_in_real_postgres(
    postgres_session: AsyncSession,
) -> None:
    team = Team(name=f"Container fixture {uuid4().hex}")
    postgres_session.add(team)
    await postgres_session.flush()

    payload = TaskCreateFactory.build(tags=["Backend", "Generated"])
    repository = TaskRepository(postgres_session)
    task = await repository.create_task(
        team_id=team.id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        status=payload.status,
        assignee=payload.assignee,
        tags=payload.tags,
        external_source=None,
        external_id=None,
    )

    matching = await repository.filter_tasks(team_id=team.id, tags=["backend"])
    assert [item.id for item in matching] == [task.id]


@pytest.mark.asyncio
async def test_redis_container_accepts_async_client(redis_container) -> None:
    redis_module = pytest.importorskip("redis.asyncio")
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    client = redis_module.Redis(host=host, port=port, decode_responses=True)
    key = f"taskflow:test:{uuid4().hex}"
    try:
        assert await client.ping() is True
        await client.set(key, "ok")
        assert await client.get(key) == "ok"
    finally:
        await client.delete(key)
        await client.aclose()
