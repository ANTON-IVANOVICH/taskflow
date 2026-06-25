from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Team(TimestampMixin, Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)

    tasks: Mapped[list[Task]] = relationship(
        back_populates="team",
        lazy="raise",
    )


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("priority >= 1 AND priority <= 5", name="priority_between_1_and_5"),
        Index("ix_tasks_team_status", "team_id", "status"),
        Index("ix_tasks_assignee", "assignee"),
        Index("ix_tasks_title", "title"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(default=3, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="todo", nullable=False)
    assignee: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    external_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    team: Mapped[Team] = relationship(back_populates="tasks", lazy="raise")
    attachments: Mapped[list[TaskAttachment]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    events: Mapped[list[TaskEvent]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="raise",
    )


class TaskAttachment(Base):
    __tablename__ = "task_attachments"
    __table_args__ = (Index("ix_task_attachments_task_id", "task_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    task: Mapped[Task] = relationship(back_populates="attachments", lazy="raise")


class TaskEvent(Base):
    __tablename__ = "task_events"
    __table_args__ = (Index("ix_task_events_task_id_occurred_at", "task_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    task: Mapped[Task] = relationship(back_populates="events", lazy="raise")


class OutboxEvent(Base):
    """Transactional outbox: written in the same transaction as the business change.

    A relay worker later publishes unpublished rows to the real-time broker and marks
    them delivered, giving at-least-once delivery without losing events on broker outage.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_events_unpublished", "published_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
