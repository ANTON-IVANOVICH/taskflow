from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Body, Path, Request, status
from fastapi.responses import StreamingResponse

from app.core.deps import AdminUser, TasksReader, TasksWriter
from app.core.errors import JobNotFound
from app.schemas.jobs import (
    JobEnqueueResult,
    JobProgressItem,
    JobStatusRead,
    OutboxRelayResult,
    ReportRequest,
)
from app.workers.queue import JobRecord
from app.workers.runtime import get_task_queue

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _to_status_read(record: JobRecord) -> JobStatusRead:
    return JobStatusRead(
        job_id=record.job_id,
        name=record.name,
        status=record.status,
        progress=[
            JobProgressItem(step=item.step, total=item.total, message=item.message)
            for item in record.progress
        ],
        result=record.result,
        error=record.error,
    )


@router.post(
    "/reports",
    response_model=JobEnqueueResult,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a team report job",
)
async def enqueue_report(
    payload: Annotated[ReportRequest, Body()],
    current_user: TasksWriter,
    request: Request,
) -> JobEnqueueResult:
    del current_user
    queue = get_task_queue(request.app)
    job_id = await queue.enqueue(
        "generate_report",
        team_id=payload.team_id,
        report_format=payload.report_format,
    )
    record = queue.store.get(job_id)
    job_status = record.status if record is not None else "queued"
    return JobEnqueueResult(job_id=job_id, status=job_status)


@router.get(
    "/{job_id}",
    response_model=JobStatusRead,
    summary="Get job status and result",
)
async def get_job_status(
    job_id: Annotated[str, Path(description="Job identifier")],
    current_user: TasksReader,
    request: Request,
) -> JobStatusRead:
    del current_user
    queue = get_task_queue(request.app)
    record = queue.store.get(job_id)
    if record is None:
        raise JobNotFound(job_id)
    return _to_status_read(record)


@router.get(
    "/{job_id}/events",
    summary="Stream job progress as Server-Sent Events",
)
async def stream_job_events(
    job_id: Annotated[str, Path(description="Job identifier")],
    current_user: TasksReader,
    request: Request,
) -> StreamingResponse:
    del current_user
    queue = get_task_queue(request.app)
    record = queue.store.get(job_id)
    if record is None:
        raise JobNotFound(job_id)

    async def event_stream() -> AsyncGenerator[str, None]:
        for item in record.progress:
            data = json.dumps(
                {"step": item.step, "total": item.total, "message": item.message},
                ensure_ascii=False,
            )
            yield f"event: progress\ndata: {data}\n\n"
        terminal = json.dumps(
            {"status": record.status, "result": record.result, "error": record.error},
            ensure_ascii=False,
        )
        yield f"event: {record.status}\ndata: {terminal}\n\n"

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


@router.post(
    "/outbox/relay",
    response_model=OutboxRelayResult,
    summary="Relay pending transactional outbox events",
)
async def relay_outbox_events(
    current_user: AdminUser,
    request: Request,
) -> OutboxRelayResult:
    del current_user
    queue = get_task_queue(request.app)
    job_id = await queue.enqueue("relay_outbox")
    record = queue.store.get(job_id)
    published = 0
    if record is not None and isinstance(record.result, dict):
        published = int(record.result.get("published", 0))
    return OutboxRelayResult(published=published)
