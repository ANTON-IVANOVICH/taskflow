"""Task queue abstraction with an ARQ/Redis backend and an in-process eager fallback.

When a Redis-backed ARQ pool is available jobs are enqueued for a separate worker process.
When it is not (local dev, tests, CI) the queue runs the handler eagerly in-process and
records its result/progress in an in-memory store — analogous to Celery's ``task_always_eager``.
Either way callers get a ``job_id`` and can poll status the same way.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("taskflow.workers")

ProgressReporter = Callable[[int, int, str], Awaitable[None]]


@dataclass
class JobContext:
    """Passed to every job handler. ``report`` records progress for status/SSE consumers."""

    job_id: str
    report: ProgressReporter
    redis: Any | None = None
    broker: Any | None = None


JobHandler = Callable[..., Awaitable[Any]]

JOB_QUEUED = "queued"
JOB_IN_PROGRESS = "in_progress"
JOB_COMPLETE = "complete"
JOB_FAILED = "failed"


@dataclass
class JobProgress:
    step: int
    total: int
    message: str


@dataclass
class JobRecord:
    job_id: str
    name: str
    status: str = JOB_QUEUED
    progress: list[JobProgress] = field(default_factory=list)
    result: Any | None = None
    error: str | None = None


class JobStore:
    """In-memory registry of job state. Single-process; ARQ uses Redis for the real thing."""

    def __init__(self) -> None:
        self._records: dict[str, JobRecord] = {}

    def create(self, job_id: str, name: str) -> JobRecord:
        record = JobRecord(job_id=job_id, name=name)
        self._records[job_id] = record
        return record

    def get(self, job_id: str) -> JobRecord | None:
        return self._records.get(job_id)

    def set_status(self, job_id: str, status: str) -> None:
        record = self._records.get(job_id)
        if record is not None:
            record.status = status

    def add_progress(self, job_id: str, step: int, total: int, message: str) -> None:
        record = self._records.get(job_id)
        if record is not None:
            record.progress.append(JobProgress(step=step, total=total, message=message))

    def complete(self, job_id: str, result: Any) -> None:
        record = self._records.get(job_id)
        if record is not None:
            record.status = JOB_COMPLETE
            record.result = result

    def fail(self, job_id: str, error: str) -> None:
        record = self._records.get(job_id)
        if record is not None:
            record.status = JOB_FAILED
            record.error = error


class TaskQueue:
    def __init__(
        self,
        *,
        handlers: Mapping[str, JobHandler],
        store: JobStore | None = None,
        eager: bool = True,
        arq_pool: Any | None = None,
        redis: Any | None = None,
        broker: Any | None = None,
        queue_name: str = "taskflow:jobs",
    ) -> None:
        self._handlers = dict(handlers)
        self.store = store or JobStore()
        self.eager = eager or arq_pool is None
        self._arq_pool = arq_pool
        self._redis = redis
        self._broker = broker
        self._queue_name = queue_name
        self.processed = 0
        self.failed = 0

    @property
    def handlers(self) -> Mapping[str, JobHandler]:
        return self._handlers

    async def enqueue(self, name: str, /, **kwargs: Any) -> str:
        if name not in self._handlers:
            raise KeyError(f"Unknown job: {name}")
        job_id = secrets.token_urlsafe(12)
        self.store.create(job_id, name)

        if not self.eager and self._arq_pool is not None:
            await self._arq_pool.enqueue_job(name, _job_id=job_id, **kwargs)
            return job_id

        await self._run_eager(job_id=job_id, name=name, kwargs=kwargs)
        return job_id

    async def _run_eager(self, *, job_id: str, name: str, kwargs: dict[str, Any]) -> None:
        self.store.set_status(job_id, JOB_IN_PROGRESS)

        async def report(step: int, total: int, message: str) -> None:
            self.store.add_progress(job_id, step, total, message)

        ctx = JobContext(job_id=job_id, report=report, redis=self._redis, broker=self._broker)
        try:
            result = await self._handlers[name](ctx, **kwargs)
        except Exception as exc:  # noqa: BLE001 - record failure, never crash the request
            logger.exception("job_failed", extra={"job": name, "job_id": job_id})
            self.store.fail(job_id, str(exc))
            self.failed += 1
            return
        self.store.complete(job_id, result)
        self.processed += 1

    async def close(self) -> None:
        pool = self._arq_pool
        if pool is not None:
            close_method = getattr(pool, "aclose", None) or getattr(pool, "close", None)
            if close_method is not None:
                result = close_method()
                if hasattr(result, "__await__"):
                    await result
