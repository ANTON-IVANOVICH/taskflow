"""Periodic job scheduler for cron-like work (outbox relay, cleanup).

Uses APScheduler's ``AsyncIOScheduler`` when installed, otherwise falls back to a minimal
asyncio interval loop so the feature degrades instead of disappearing. In multi-instance
deployments run this in a single dedicated process (or use a distributed lock) to avoid
duplicate firings — same caveat as Celery Beat.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger("taskflow.workers")

PeriodicJob = Callable[[], Awaitable[object]]


@dataclass
class _ScheduledJob:
    job_id: str
    func: PeriodicJob
    interval_seconds: int


class PeriodicScheduler:
    def __init__(self) -> None:
        self._jobs: list[_ScheduledJob] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._apscheduler: object | None = None
        self._running = False

    def add_interval_job(self, func: PeriodicJob, *, interval_seconds: int, job_id: str) -> None:
        self._jobs.append(
            _ScheduledJob(job_id=job_id, func=func, interval_seconds=interval_seconds)
        )

    async def start(self) -> None:
        if self._running or not self._jobs:
            return
        self._running = True
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler

            scheduler = AsyncIOScheduler(timezone="UTC")
            for job in self._jobs:
                scheduler.add_job(
                    job.func,
                    "interval",
                    seconds=job.interval_seconds,
                    id=job.job_id,
                    replace_existing=True,
                )
            scheduler.start()
            self._apscheduler = scheduler
            logger.info("scheduler_started", extra={"backend": "apscheduler"})
        except ModuleNotFoundError:
            for job in self._jobs:
                self._tasks.append(asyncio.create_task(self._run_interval(job)))
            logger.info("scheduler_started", extra={"backend": "asyncio"})

    async def _run_interval(self, job: _ScheduledJob) -> None:
        while True:
            await asyncio.sleep(job.interval_seconds)
            try:
                await job.func()
            except Exception:  # noqa: BLE001 - keep the loop alive across failures
                logger.exception("periodic_job_failed", extra={"job_id": job.job_id})

    async def stop(self) -> None:
        self._running = False
        scheduler = self._apscheduler
        if scheduler is not None:
            scheduler.shutdown(wait=False)  # type: ignore[attr-defined]
            self._apscheduler = None
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
