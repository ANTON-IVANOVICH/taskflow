from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import Select, func, or_, select

from app.db.models import Task, TaskAttachment, TaskEvent, Team
from app.repositories.base import BaseRepository


class TaskRepository(BaseRepository[Task]):
    model = Task

    async def get_task(self, task_id: int) -> Task | None:
        return await self.session.get(Task, task_id)

    async def team_exists(self, team_id: int) -> bool:
        stmt = select(Team.id).where(Team.id == team_id).limit(1)
        return (await self.session.scalar(stmt)) is not None

    async def list_tasks(
        self,
        *,
        limit: int,
        offset: int,
        tags: list[str] | None = None,
        team_id: int | None = None,
        status: str | None = None,
        assignee: str | None = None,
        search: str | None = None,
        preselected_ids: set[int] | None = None,
    ) -> list[Task]:
        stmt = self._build_filtered_stmt(
            team_id=team_id,
            status=status,
            assignee=assignee,
            search=search,
            preselected_ids=preselected_ids,
        )
        tasks = list((await self.session.scalars(stmt)).all())
        tasks = self._apply_tags_filter(tasks=tasks, tags=tags)
        return tasks[offset : offset + limit]

    async def filter_tasks(
        self,
        *,
        tags: list[str] | None = None,
        team_id: int | None = None,
        status: str | None = None,
        assignee: str | None = None,
        search: str | None = None,
        preselected_ids: set[int] | None = None,
    ) -> list[Task]:
        stmt = self._build_filtered_stmt(
            team_id=team_id,
            status=status,
            assignee=assignee,
            search=search,
            preselected_ids=preselected_ids,
        )
        tasks = list((await self.session.scalars(stmt)).all())
        return self._apply_tags_filter(tasks=tasks, tags=tags)

    async def create_task(
        self,
        *,
        team_id: int,
        title: str,
        description: str | None,
        priority: int,
        status: str,
        assignee: str | None,
        tags: list[str],
        external_source: str | None,
        external_id: str | None,
    ) -> Task:
        task = Task(
            team_id=team_id,
            title=title,
            description=description,
            priority=priority,
            status=status,
            assignee=assignee,
            tags=tags,
            external_source=external_source,
            external_id=external_id,
        )
        self.session.add(task)
        await self.session.flush()
        return task

    async def update_task(self, task: Task, data: dict[str, object]) -> Task:
        for key, value in data.items():
            setattr(task, key, value)
        await self.session.flush()
        return task

    async def create_attachment(
        self,
        *,
        task_id: int,
        filename: str,
        content_type: str | None,
        content: bytes,
    ) -> TaskAttachment:
        attachment = TaskAttachment(
            task_id=task_id,
            filename=filename,
            content_type=content_type,
            size=len(content),
            content=content,
        )
        self.session.add(attachment)
        await self.session.flush()
        return attachment

    async def get_attachment(
        self,
        *,
        task_id: int,
        attachment_id: int,
    ) -> TaskAttachment | None:
        stmt = (
            select(TaskAttachment)
            .where(TaskAttachment.id == attachment_id, TaskAttachment.task_id == task_id)
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def list_events(self, *, task_id: int, limit: int) -> list[TaskEvent]:
        stmt = (
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id)
            .order_by(TaskEvent.occurred_at.desc(), TaskEvent.id.desc())
            .limit(limit)
        )
        events = list((await self.session.scalars(stmt)).all())
        events.reverse()
        return events

    async def create_event(
        self,
        *,
        task_id: int,
        event_type: str,
        payload: dict[str, object] | None = None,
    ) -> TaskEvent:
        event = TaskEvent(
            task_id=task_id,
            event_type=event_type,
            payload=payload or {},
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def get_task_ids_by_text_search(
        self,
        query: str,
        *,
        limit: int = 100,
    ) -> set[int]:
        stmt = (
            select(Task.id)
            .where(
                or_(
                    Task.title.ilike(f"%{query}%"),
                    func.coalesce(Task.description, "").ilike(f"%{query}%"),
                )
            )
            .order_by(Task.created_at.desc(), Task.id.desc())
            .limit(limit)
        )
        rows = (await self.session.scalars(stmt)).all()
        return set(rows)

    def _build_filtered_stmt(
        self,
        *,
        team_id: int | None,
        status: str | None,
        assignee: str | None,
        search: str | None,
        preselected_ids: set[int] | None,
    ) -> Select[tuple[Task]]:
        stmt = select(Task)
        if team_id is not None:
            stmt = stmt.where(Task.team_id == team_id)
        if status is not None:
            stmt = stmt.where(Task.status == status)
        if assignee is not None:
            stmt = stmt.where(func.lower(Task.assignee) == assignee.strip().lower())
        if search is not None and search.strip():
            token = search.strip()
            stmt = stmt.where(
                or_(
                    Task.title.ilike(f"%{token}%"),
                    func.coalesce(Task.description, "").ilike(f"%{token}%"),
                )
            )
        if preselected_ids is not None:
            if not preselected_ids:
                return stmt.where(Task.id == -1)
            stmt = stmt.where(Task.id.in_(preselected_ids))
        return stmt.order_by(Task.created_at.desc(), Task.id.desc())

    @staticmethod
    def _apply_tags_filter(tasks: Iterable[Task], tags: list[str] | None) -> list[Task]:
        if not tags:
            return list(tasks)
        tag_set = {tag.lower() for tag in tags}
        return [task for task in tasks if tag_set.intersection({tag.lower() for tag in task.tags})]
