from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

TaskStatus = Literal["todo", "in_progress", "done", "blocked"]
TaskEventType = Literal["task_created", "task_updated", "attachment_uploaded", "task_imported"]
TaskDescriptionFormat = Literal["markdown", "html"]
TaskImportProvider = Literal["jira", "trello", "asana", "linear", "clickup", "github"]


class TaskBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    priority: int = Field(default=3, ge=1, le=5)
    status: TaskStatus = "todo"
    assignee: str | None = Field(default=None, max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        normalized = []
        for tag in value:
            tag_value = tag.strip().lower()
            if tag_value and tag_value not in normalized:
                normalized.append(tag_value)
        return normalized


class TaskCreate(TaskBase):
    pass


class TaskImportItem(TaskBase):
    external_id: str | None = Field(default=None, min_length=1, max_length=120)


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    priority: int | None = Field(default=None, ge=1, le=5)
    status: TaskStatus | None = None
    assignee: str | None = Field(default=None, max_length=120)
    tags: list[str] | None = Field(default=None, max_length=10)


class TaskRead(TaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    team_id: int
    created_at: datetime

    @computed_field(return_type=bool)
    @property
    def is_urgent(self) -> bool:
        return self.priority >= 5


class TaskAttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    filename: str
    content_type: str | None = None
    size: int = Field(ge=0)
    uploaded_at: datetime


class TaskEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    event_type: TaskEventType
    payload: dict[str, object] = Field(default_factory=dict)
    occurred_at: datetime


class TaskDescriptionPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: TaskDescriptionFormat = "markdown"
    content: str = Field(min_length=1, max_length=10000)


class TaskImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: TaskImportProvider | None = None
    payload: list[TaskImportItem] = Field(min_length=1, max_length=100)


class TaskImportPayloadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: list[TaskImportItem] = Field(min_length=1, max_length=100)


class TaskImportResult(BaseModel):
    provider: TaskImportProvider | None = None
    imported: int = Field(ge=0)
    tasks: list[TaskRead] = Field(default_factory=list)
