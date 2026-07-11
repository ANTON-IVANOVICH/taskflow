"""ARQ worker entrypoint.

Run a worker process with::

    arq app.workers.settings.WorkerSettings

This is only used when ``REDIS_URL`` is configured; without Redis the app runs jobs eagerly
in-process and this module is never imported by the request path. ARQ is an optional dependency,
so importing it is guarded.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings
from app.workers.jobs import (
    JOB_HANDLERS,
    deliver_webhook,
    generate_report,
    process_webhook_event,
    purge_published_outbox,
    relay_outbox,
    send_welcome_email,
)
from app.workers.queue import JobContext

logger = logging.getLogger("taskflow.workers")
settings = get_settings()


def _arq_handler(name: str) -> Any:
    """Adapt an ARQ ``(ctx, ...)`` call to our ``JobContext``-based handler signature."""

    handler = JOB_HANDLERS[name]

    async def runner(ctx: dict[str, Any], **kwargs: Any) -> Any:
        async def report(step: int, total: int, message: str) -> None:
            redis = ctx.get("redis")
            job_id = ctx.get("job_id")
            if redis is not None and job_id is not None:
                await redis.publish(
                    f"{settings.realtime_channel_prefix}:job:{job_id}",
                    f'{{"step": {step}, "total": {total}, "message": "{message}"}}',
                )

        job_ctx = JobContext(
            job_id=str(ctx.get("job_id", "")),
            report=report,
            redis=ctx.get("redis"),
            broker=ctx.get("broker"),
        )
        return await handler(job_ctx, **kwargs)

    runner.__name__ = name
    return runner


async def _startup(ctx: dict[str, Any]) -> None:
    logger.info("arq_worker_started")


async def _shutdown(ctx: dict[str, Any]) -> None:
    logger.info("arq_worker_stopped")


try:
    from arq.connections import RedisSettings

    class WorkerSettings:
        functions = [
            _arq_handler("generate_report"),
            _arq_handler("relay_outbox"),
            _arq_handler("purge_published_outbox"),
            _arq_handler("send_welcome_email"),
            _arq_handler("process_webhook_event"),
            _arq_handler("deliver_webhook"),
        ]
        on_startup = _startup
        on_shutdown = _shutdown
        max_jobs = settings.worker_max_jobs
        job_timeout = settings.worker_job_timeout_seconds
        keep_result = settings.worker_job_ttl_seconds

        @staticmethod
        def redis_settings() -> Any:
            return RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379")

except ModuleNotFoundError:  # pragma: no cover - arq not installed
    WorkerSettings = None  # type: ignore[assignment,misc]


__all__ = [
    "WorkerSettings",
    "generate_report",
    "purge_published_outbox",
    "relay_outbox",
    "send_welcome_email",
    "process_webhook_event",
    "deliver_webhook",
]
