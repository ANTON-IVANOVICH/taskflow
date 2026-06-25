"""Wiring for the worker layer: the default in-process queue and lifespan builders.

``default_task_queue`` is a module-level eager queue used when the app lifespan never runs
(tests, imports). At startup the lifespan builds an ARQ-backed queue (if Redis is available)
and stores it on ``app.state.task_queue``; :func:`get_task_queue` prefers that and otherwise
returns the default, so request handlers don't care which backend is live.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings
from app.workers.jobs import JOB_HANDLERS
from app.workers.queue import TaskQueue

logger = logging.getLogger("taskflow.workers")

default_task_queue = TaskQueue(handlers=JOB_HANDLERS, eager=True)


def get_task_queue(app: Any) -> TaskQueue:
    queue = getattr(app.state, "task_queue", None)
    if isinstance(queue, TaskQueue):
        return queue
    return default_task_queue


async def build_task_queue(*, redis: Any | None, broker: Any | None) -> TaskQueue:
    """Build the runtime queue: ARQ-backed when Redis + arq are available, else eager."""

    settings = get_settings()
    eager_override = settings.worker_eager
    if eager_override is True or redis is None:
        return TaskQueue(
            handlers=JOB_HANDLERS,
            eager=True,
            redis=redis,
            broker=broker,
            queue_name=settings.worker_queue_name,
        )

    arq_pool: Any | None = None
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url or ""))
    except Exception:  # noqa: BLE001 - fall back to eager if the broker can't be reached
        logger.warning("arq_pool_unavailable_falling_back_to_eager")
        arq_pool = None

    return TaskQueue(
        handlers=JOB_HANDLERS,
        eager=arq_pool is None,
        arq_pool=arq_pool,
        redis=redis,
        broker=broker,
        queue_name=settings.worker_queue_name,
    )
