from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()
database_url = settings.postgres_dsn or settings.database_url

_engine_kwargs: dict[str, object] = {
    "echo": settings.db_echo or settings.app_debug,
    "pool_pre_ping": settings.db_pool_pre_ping,
}

if not database_url.startswith("sqlite"):
    _engine_kwargs.update(
        {
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_recycle": settings.db_pool_recycle_seconds,
        }
    )

engine = create_async_engine(
    database_url,
    **_engine_kwargs,
)

async_session_maker = async_sessionmaker(
    engine,
    expire_on_commit=False,
    autoflush=False,
    class_=AsyncSession,
)
