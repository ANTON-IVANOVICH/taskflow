from __future__ import annotations

import re
from collections.abc import Iterable
from html import escape

from app.core.errors import TaskAttachmentNotFound, TaskNotFound, TeamNotFound
from app.db.clients import DataClients, publish_task_event
from app.db.models import Task, TaskAttachment, TaskEvent
from app.db.search import MeiliSearchGateway
from app.db.uow import SqlAlchemyUnitOfWork
from app.schemas.tasks import (
    TaskAttachmentRead,
    TaskCreate,
    TaskDescriptionPreviewIn,
    TaskEventRead,
    TaskImportItem,
    TaskImportProvider,
    TaskRead,
    TaskStatus,
    TaskUpdate,
)


async def list_tasks(
    *,
    uow: SqlAlchemyUnitOfWork,
    limit: int,
    offset: int,
    tags: list[str] | None = None,
    team_id: int | None = None,
    status: TaskStatus | None = None,
    assignee: str | None = None,
    search: str | None = None,
    search_gateway: MeiliSearchGateway | None = None,
) -> list[TaskRead]:
    preselected_ids = await _resolve_search_ids(
        uow=uow,
        search=search,
        search_gateway=search_gateway,
        limit=max(limit + offset, 100),
    )
    tasks = await uow.tasks.list_tasks(
        limit=limit,
        offset=offset,
        tags=tags,
        team_id=team_id,
        status=status,
        assignee=assignee,
        search=search if preselected_ids is None else None,
        preselected_ids=preselected_ids,
    )
    return [_to_task_read(task) for task in tasks]


async def filter_tasks(
    *,
    uow: SqlAlchemyUnitOfWork,
    tags: list[str] | None = None,
    team_id: int | None = None,
    status: TaskStatus | None = None,
    assignee: str | None = None,
    search: str | None = None,
    search_gateway: MeiliSearchGateway | None = None,
) -> list[TaskRead]:
    preselected_ids = await _resolve_search_ids(
        uow=uow,
        search=search,
        search_gateway=search_gateway,
        limit=1000,
    )
    tasks = await uow.tasks.filter_tasks(
        tags=tags,
        team_id=team_id,
        status=status,
        assignee=assignee,
        search=search if preselected_ids is None else None,
        preselected_ids=preselected_ids,
    )
    return [_to_task_read(task) for task in tasks]


async def get_task(uow: SqlAlchemyUnitOfWork, task_id: int) -> TaskRead:
    task = await uow.tasks.get_task(task_id)
    if task is None:
        raise TaskNotFound(task_id)
    return _to_task_read(task)


async def create_task(
    *,
    uow: SqlAlchemyUnitOfWork,
    payload: TaskCreate,
    team_id: int,
    source: TaskImportProvider | None = None,
    external_id: str | None = None,
    clients: DataClients | None = None,
) -> TaskRead:
    if not await uow.tasks.team_exists(team_id):
        raise TeamNotFound(team_id)

    task = await uow.tasks.create_task(
        team_id=team_id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        status=payload.status,
        assignee=payload.assignee,
        tags=payload.tags,
        external_source=source,
        external_id=external_id,
    )
    created_payload: dict[str, object] = {
        "title": task.title,
        "team_id": task.team_id,
        "priority": task.priority,
    }
    if source is not None:
        created_payload["source"] = source
    if external_id is not None:
        created_payload["external_id"] = external_id

    created_event = await uow.tasks.create_event(
        task_id=task.id,
        event_type="task_created",
        payload=created_payload,
    )
    imported_event: TaskEvent | None = None
    if source is not None:
        imported_payload: dict[str, object] = {"source": source}
        if external_id is not None:
            imported_payload["external_id"] = external_id
        imported_event = await uow.tasks.create_event(
            task_id=task.id,
            event_type="task_imported",
            payload=imported_payload,
        )
    await uow.commit()

    await _emit_events(clients=clients, events=[created_event, imported_event])
    return _to_task_read(task)


async def update_task(
    *,
    uow: SqlAlchemyUnitOfWork,
    task_id: int,
    payload: TaskUpdate,
    clients: DataClients | None = None,
) -> TaskRead:
    task = await uow.tasks.get_task(task_id)
    if task is None:
        raise TaskNotFound(task_id)

    update_payload = payload.model_dump(exclude_unset=True)
    updated = await uow.tasks.update_task(task=task, data=update_payload)
    event = await uow.tasks.create_event(
        task_id=task_id,
        event_type="task_updated",
        payload={"changed_fields": sorted(update_payload.keys())},
    )
    await uow.commit()

    await _emit_events(clients=clients, events=[event])
    return _to_task_read(updated)


async def add_attachment(
    *,
    uow: SqlAlchemyUnitOfWork,
    task_id: int,
    filename: str | None,
    content_type: str | None,
    content: bytes,
    clients: DataClients | None = None,
) -> TaskAttachmentRead:
    task = await uow.tasks.get_task(task_id)
    if task is None:
        raise TaskNotFound(task_id)

    attachment = await uow.tasks.create_attachment(
        task_id=task_id,
        filename=filename or "attachment.bin",
        content_type=content_type,
        content=content,
    )
    event = await uow.tasks.create_event(
        task_id=task_id,
        event_type="attachment_uploaded",
        payload={
            "attachment_id": attachment.id,
            "filename": attachment.filename,
            "size": attachment.size,
        },
    )
    await uow.commit()

    await _emit_events(clients=clients, events=[event])
    return _to_task_attachment_read(attachment)


async def get_attachment_with_content(
    *,
    uow: SqlAlchemyUnitOfWork,
    task_id: int,
    attachment_id: int,
) -> tuple[TaskAttachmentRead, bytes]:
    task = await uow.tasks.get_task(task_id)
    if task is None:
        raise TaskNotFound(task_id)

    attachment = await uow.tasks.get_attachment(task_id=task_id, attachment_id=attachment_id)
    if attachment is None:
        raise TaskAttachmentNotFound(task_id=task_id, attachment_id=attachment_id)
    return _to_task_attachment_read(attachment), attachment.content


async def list_task_events(
    *,
    uow: SqlAlchemyUnitOfWork,
    task_id: int,
    limit: int = 20,
) -> list[TaskEventRead]:
    task = await uow.tasks.get_task(task_id)
    if task is None:
        raise TaskNotFound(task_id)
    events = await uow.tasks.list_events(task_id=task_id, limit=limit)
    return [_to_task_event_read(event) for event in events]


async def import_tasks(
    *,
    uow: SqlAlchemyUnitOfWork,
    payload: list[TaskImportItem],
    team_id: int,
    provider: TaskImportProvider | None = None,
    clients: DataClients | None = None,
) -> list[TaskRead]:
    if not await uow.tasks.team_exists(team_id):
        raise TeamNotFound(team_id)

    imported: list[TaskRead] = []
    events: list[TaskEvent] = []
    for item in payload:
        task_payload = TaskCreate(**item.model_dump(exclude={"external_id"}))
        task = await uow.tasks.create_task(
            team_id=team_id,
            title=task_payload.title,
            description=task_payload.description,
            priority=task_payload.priority,
            status=task_payload.status,
            assignee=task_payload.assignee,
            tags=task_payload.tags,
            external_source=provider,
            external_id=item.external_id,
        )
        created_payload: dict[str, object] = {
            "title": task.title,
            "team_id": task.team_id,
            "priority": task.priority,
        }
        if provider is not None:
            created_payload["source"] = provider
        if item.external_id is not None:
            created_payload["external_id"] = item.external_id

        events.append(
            await uow.tasks.create_event(
                task_id=task.id,
                event_type="task_created",
                payload=created_payload,
            )
        )
        if provider is not None:
            imported_payload: dict[str, object] = {"source": provider}
            if item.external_id is not None:
                imported_payload["external_id"] = item.external_id
            events.append(
                await uow.tasks.create_event(
                    task_id=task.id,
                    event_type="task_imported",
                    payload=imported_payload,
                )
            )
        imported.append(_to_task_read(task))

    await uow.commit()
    await _emit_events(clients=clients, events=events)
    return imported


def preview_task_description(payload: TaskDescriptionPreviewIn) -> str:
    if payload.format == "html":
        return _sanitize_html(payload.content)
    return _render_markdown_to_html(payload.content)


async def _resolve_search_ids(
    *,
    uow: SqlAlchemyUnitOfWork,
    search: str | None,
    search_gateway: MeiliSearchGateway | None,
    limit: int,
) -> set[int] | None:
    if search is None or not search.strip():
        return None
    if search_gateway is not None:
        ids = await search_gateway.search_task_ids(search, limit=limit)
        if ids is not None:
            return ids
    return await uow.tasks.get_task_ids_by_text_search(search, limit=limit)


def _to_task_read(task: Task) -> TaskRead:
    return TaskRead.model_validate(task)


def _to_task_attachment_read(attachment: TaskAttachment) -> TaskAttachmentRead:
    return TaskAttachmentRead.model_validate(attachment)


def _to_task_event_read(event: TaskEvent) -> TaskEventRead:
    return TaskEventRead.model_validate(event)


async def _emit_events(
    *,
    clients: DataClients | None,
    events: Iterable[TaskEvent | None],
) -> None:
    if clients is None:
        return
    for event in events:
        if event is None:
            continue
        try:
            await publish_task_event(clients, _to_task_event_read(event))
        except Exception:  # noqa: BLE001
            continue


def _render_markdown_to_html(markdown: str) -> str:
    blocks: list[str] = []
    list_buffer: list[str] = []

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            if list_buffer:
                blocks.append("<ul>" + "".join(list_buffer) + "</ul>")
                list_buffer = []
            continue

        if line.startswith("- "):
            list_buffer.append(f"<li>{_render_inline_markdown(line[2:].strip())}</li>")
            continue

        if list_buffer:
            blocks.append("<ul>" + "".join(list_buffer) + "</ul>")
            list_buffer = []

        if line.startswith("### "):
            blocks.append(f"<h3>{_render_inline_markdown(line[4:].strip())}</h3>")
            continue
        if line.startswith("## "):
            blocks.append(f"<h2>{_render_inline_markdown(line[3:].strip())}</h2>")
            continue
        if line.startswith("# "):
            blocks.append(f"<h1>{_render_inline_markdown(line[2:].strip())}</h1>")
            continue

        blocks.append(f"<p>{_render_inline_markdown(line)}</p>")

    if list_buffer:
        blocks.append("<ul>" + "".join(list_buffer) + "</ul>")

    return "".join(blocks)


def _render_inline_markdown(text: str) -> str:
    safe = escape(text)
    safe = re.sub(r"`([^`]+)`", r"<code>\1</code>", safe)
    safe = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", safe)
    safe = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", safe)

    def replace_link(match: re.Match[str]) -> str:
        label = match.group(1)
        url = match.group(2).strip()
        if url.startswith(("http://", "https://", "mailto:")):
            return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}</a>'
        return label

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace_link, safe)


def _sanitize_html(content: str) -> str:
    sanitized = content
    sanitized = re.sub(
        r"<\s*(script|style|iframe|object|embed|link|meta)[^>]*>.*?<\s*/\s*\1\s*>",
        "",
        sanitized,
        flags=re.IGNORECASE | re.DOTALL,
    )
    sanitized = re.sub(
        r"\s+on[a-zA-Z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)",
        "",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(?i)\s+href\s*=\s*(['\"])\s*javascript:[^'\"]*\1",
        ' href="#"',
        sanitized,
    )
    sanitized = re.sub(
        r"(?i)\s+src\s*=\s*(['\"])\s*javascript:[^'\"]*\1",
        "",
        sanitized,
    )
    return sanitized
