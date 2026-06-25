from __future__ import annotations

from fastapi import APIRouter, Request

from app.db.bootstrap import ensure_schema_initialized
from app.db.session import async_session_maker
from app.db.uow import SqlAlchemyUnitOfWork
from app.schemas.jobs import WorkerMetricsRead
from app.websockets.realtime import connection_manager
from app.workers.runtime import get_task_queue

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", summary="Readiness probe")
async def ready() -> dict[str, str]:
    return {"status": "ready"}


@router.get("/worker-metrics", response_model=WorkerMetricsRead, summary="Worker/realtime metrics")
async def worker_metrics(request: Request) -> WorkerMetricsRead:
    queue = get_task_queue(request.app)
    await ensure_schema_initialized()
    async with async_session_maker() as session:
        uow = SqlAlchemyUnitOfWork(session)
        outbox_pending = await uow.outbox.count_unpublished()
    return WorkerMetricsRead(
        ws_active_connections=connection_manager.active_connections,
        ws_active_rooms=connection_manager.active_rooms,
        jobs_processed=queue.processed,
        jobs_failed=queue.failed,
        outbox_pending=outbox_pending,
    )
