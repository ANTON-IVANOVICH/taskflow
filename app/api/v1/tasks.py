import json
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, Path, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from app.core.deps import Paginator, TasksReader, TasksWriter, UoWDep
from app.schemas.jobs import DashboardRead
from app.schemas.tasks import (
    TaskAttachmentRead,
    TaskCreate,
    TaskDescriptionPreviewIn,
    TaskImportIn,
    TaskImportResult,
    TaskRead,
    TaskStatus,
    TaskUpdate,
)
from app.services import tasks as task_service
from app.websockets.realtime import broadcast_task_event, task_room

router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
    responses={404: {"description": "Task not found"}},
)


@router.get("/", response_model=list[TaskRead], summary="List tasks")
async def list_tasks(
    paginator: Annotated[Paginator, Depends()],
    current_user: TasksReader,
    uow: UoWDep,
    request: Request,
    tags: Annotated[list[str] | None, Query(description="Filter by tags")] = None,
    team_id: Annotated[int | None, Query(ge=1, description="Filter by team id")] = None,
    status: Annotated[TaskStatus | None, Query(description="Filter by task status")] = None,
    assignee: Annotated[
        str | None,
        Query(min_length=1, max_length=120, description="Filter by assignee email"),
    ] = None,
    search: Annotated[
        str | None,
        Query(min_length=1, max_length=200, description="Full-text search query"),
    ] = None,
) -> list[TaskRead]:
    del current_user
    return await task_service.list_tasks(
        uow=uow,
        limit=paginator.limit,
        offset=paginator.offset,
        tags=tags,
        team_id=team_id,
        status=status,
        assignee=assignee,
        search=search,
        search_gateway=getattr(request.app.state, "search_gateway", None),
    )


@router.get("/export.csv", summary="Export tasks report as CSV")
async def export_tasks_csv(
    current_user: TasksReader,
    uow: UoWDep,
    request: Request,
    team_id: Annotated[int | None, Query(ge=1, description="Filter by team id")] = None,
    status: Annotated[TaskStatus | None, Query(description="Filter by task status")] = None,
    assignee: Annotated[
        str | None,
        Query(min_length=1, max_length=120, description="Filter by assignee email"),
    ] = None,
) -> StreamingResponse:
    del current_user
    tasks = await task_service.filter_tasks(
        uow=uow,
        team_id=team_id,
        status=status,
        assignee=assignee,
        search_gateway=getattr(request.app.state, "search_gateway", None),
    )

    async def generate() -> AsyncGenerator[str, None]:
        yield "id,title,status,assignee,priority,team_id,created_at,tags\n"
        for task in tasks:
            assignee_value = task.assignee or ""
            tags_value = "|".join(task.tags)
            created_at_value = task.created_at.isoformat()
            yield (
                f"{task.id},{task.title},{task.status},{assignee_value},"
                f"{task.priority},{task.team_id},{created_at_value},{tags_value}\n"
            )

    return StreamingResponse(generate(), media_type="text/csv")


@router.post(
    "/",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create task",
)
async def create_task(
    payload: Annotated[
        TaskCreate,
        Body(
            examples={
                "simple": {
                    "summary": "Default priority",
                    "value": {"title": "Buy milk", "priority": 3, "tags": ["home"]},
                },
                "urgent": {
                    "summary": "High priority",
                    "value": {"title": "Fix prod", "priority": 5, "tags": ["backend"]},
                },
            }
        ),
    ],
    current_user: TasksWriter,
    uow: UoWDep,
    request: Request,
    team_id: Annotated[int, Query(ge=1, description="Team ID for task ownership")] = 1,
) -> TaskRead:
    del current_user
    return await task_service.create_task(
        uow=uow,
        payload=payload,
        team_id=team_id,
        clients=getattr(request.app.state, "data_clients", None),
    )


@router.post(
    "/import",
    response_model=TaskImportResult,
    status_code=status.HTTP_201_CREATED,
    summary="Import tasks from wrapped payload",
)
async def import_tasks(
    payload: Annotated[
        TaskImportIn,
        Body(
            examples={
                "jira": {
                    "summary": "Import tasks from Jira export",
                    "value": {
                        "provider": "jira",
                        "payload": [
                            {
                                "external_id": "JIRA-2451",
                                "title": "Document API contract",
                                "priority": 4,
                                "tags": ["docs", "api"],
                            },
                            {
                                "external_id": "JIRA-2452",
                                "title": "Stabilize background workers",
                                "priority": 5,
                                "tags": ["ops", "backend"],
                            },
                        ],
                    },
                }
            }
        ),
    ],
    current_user: TasksWriter,
    uow: UoWDep,
    request: Request,
    team_id: Annotated[int, Query(ge=1, description="Team ID for imported tasks")] = 1,
) -> TaskImportResult:
    del current_user
    imported = await task_service.import_tasks(
        uow=uow,
        payload=payload.payload,
        team_id=team_id,
        provider=payload.provider,
        clients=getattr(request.app.state, "data_clients", None),
    )
    return TaskImportResult(
        provider=payload.provider,
        imported=len(imported),
        tasks=imported,
    )


@router.post(
    "/description/preview",
    summary="Preview task description",
    response_class=HTMLResponse,
)
async def preview_task_description(
    payload: Annotated[
        TaskDescriptionPreviewIn,
        Body(
            examples={
                "markdown": {
                    "summary": "Markdown description",
                    "value": {
                        "format": "markdown",
                        "content": "# Incident\n- Investigate latency\n- Notify team",
                    },
                },
                "html": {
                    "summary": "Raw HTML description",
                    "value": {
                        "format": "html",
                        "content": "<h2>Release Notes</h2><p>Deployment at 18:00</p>",
                    },
                },
            }
        ),
    ],
    current_user: TasksWriter,
    uow: UoWDep,
) -> HTMLResponse:
    del current_user, uow
    html = task_service.preview_task_description(payload)
    return HTMLResponse(content=html)


@router.get("/dashboard", response_model=DashboardRead, summary="Team dashboard aggregate")
async def task_dashboard(
    current_user: TasksReader,
    team_id: Annotated[int | None, Query(ge=1, description="Filter dashboard by team id")] = None,
) -> DashboardRead:
    del current_user
    return await task_service.build_dashboard(team_id=team_id)


@router.get("/{task_id}", response_model=TaskRead, summary="Get task by id")
async def get_task(
    task_id: Annotated[int, Path(ge=1, description="Task identifier")],
    current_user: TasksReader,
    uow: UoWDep,
) -> TaskRead:
    del current_user
    return await task_service.get_task(uow=uow, task_id=task_id)


@router.put("/{task_id}", response_model=TaskRead, summary="Update task")
async def update_task(
    task_id: Annotated[int, Path(ge=1, description="Task identifier")],
    payload: Annotated[TaskUpdate, Body()],
    current_user: TasksWriter,
    uow: UoWDep,
    request: Request,
    notify: Annotated[bool, Query(description="Notify task participants")] = False,
) -> TaskRead:
    del current_user
    updated = await task_service.update_task(
        uow=uow,
        task_id=task_id,
        payload=payload,
        clients=getattr(request.app.state, "data_clients", None),
    )
    await broadcast_task_event(
        request.app,
        task_room(task_id),
        {
            "type": "task_event",
            "event": "task_updated",
            "task_id": task_id,
            "status": updated.status,
            "priority": updated.priority,
            "notify": notify,
        },
    )
    return updated


@router.post(
    "/{task_id}/attachments",
    response_model=TaskAttachmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Upload attachment for task",
)
async def upload_task_attachment(
    task_id: Annotated[int, Path(ge=1, description="Task identifier")],
    attachment: Annotated[UploadFile, File(description="Attachment file")],
    current_user: TasksWriter,
    uow: UoWDep,
    request: Request,
) -> TaskAttachmentRead:
    del current_user
    content = await attachment.read()
    return await task_service.add_attachment(
        uow=uow,
        task_id=task_id,
        filename=attachment.filename,
        content_type=attachment.content_type,
        content=content,
        clients=getattr(request.app.state, "data_clients", None),
    )


@router.get(
    "/{task_id}/attachments/{attachment_id}",
    summary="Download task attachment",
    response_class=Response,
)
async def download_task_attachment(
    task_id: Annotated[int, Path(ge=1, description="Task identifier")],
    attachment_id: Annotated[int, Path(ge=1, description="Attachment identifier")],
    current_user: TasksReader,
    uow: UoWDep,
) -> Response:
    del current_user
    attachment, content = await task_service.get_attachment_with_content(
        uow=uow,
        task_id=task_id,
        attachment_id=attachment_id,
    )
    headers = {"Content-Disposition": f'attachment; filename="{attachment.filename}"'}
    media_type = attachment.content_type or "application/octet-stream"
    return Response(content=content, media_type=media_type, headers=headers)


@router.get(
    "/{task_id}/events/stream",
    summary="Stream task events",
)
async def stream_task_events(
    task_id: Annotated[int, Path(ge=1, description="Task identifier")],
    current_user: TasksReader,
    uow: UoWDep,
    limit: Annotated[int, Query(ge=1, le=100, description="How many events to stream")] = 20,
) -> StreamingResponse:
    del current_user
    events = await task_service.list_task_events(uow=uow, task_id=task_id, limit=limit)

    async def event_stream() -> AsyncGenerator[str, None]:
        for event in events:
            payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
            yield f"id: {event.id}\nevent: {event.event_type}\ndata: {payload}\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=headers,
    )
