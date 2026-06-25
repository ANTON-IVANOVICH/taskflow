from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: int = Field(ge=1)
    report_format: str = Field(default="summary", pattern="^(summary|detailed)$")


class JobEnqueueResult(BaseModel):
    job_id: str
    status: str


class JobProgressItem(BaseModel):
    step: int
    total: int
    message: str


class JobStatusRead(BaseModel):
    job_id: str
    name: str
    status: str
    progress: list[JobProgressItem] = Field(default_factory=list)
    result: object | None = None
    error: str | None = None


class OutboxRelayResult(BaseModel):
    published: int = Field(ge=0)


class DashboardRead(BaseModel):
    team_id: int | None = None
    status_counts: dict[str, int] = Field(default_factory=dict)
    recent: list[str] = Field(default_factory=list)
    pulse: dict[str, object] = Field(default_factory=dict)


class WorkerMetricsRead(BaseModel):
    ws_active_connections: int = Field(ge=0)
    ws_active_rooms: int = Field(ge=0)
    jobs_processed: int = Field(ge=0)
    jobs_failed: int = Field(ge=0)
    outbox_pending: int = Field(ge=0)
