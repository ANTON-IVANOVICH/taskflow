from typing import Annotated

from fastapi import APIRouter, Body, Path, Query, Request, status

from app.core.deps import IntegrationsWriter, UoWDep
from app.schemas.tasks import (
    TaskImportPayloadIn,
    TaskImportProvider,
    TaskImportResult,
)
from app.services import tasks as task_service

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.post(
    "/{provider}/tasks",
    response_model=TaskImportResult,
    status_code=status.HTTP_201_CREATED,
    summary="Import tasks from external provider",
)
async def import_provider_tasks(
    provider: Annotated[TaskImportProvider, Path(description="External provider name")],
    payload: Annotated[
        TaskImportPayloadIn,
        Body(
            examples={
                "provider_payload": {
                    "summary": "Wrapped list of tasks from integration webhook",
                    "value": {
                        "payload": [
                            {
                                "external_id": "IMP-1001",
                                "title": "Sync billing board",
                                "priority": 3,
                                "tags": ["billing", "sync"],
                            }
                        ]
                    },
                }
            }
        ),
    ],
    current_user: IntegrationsWriter,
    uow: UoWDep,
    request: Request,
    team_id: Annotated[int, Query(ge=1, description="Team ID for imported tasks")] = 1,
) -> TaskImportResult:
    del current_user
    imported = await task_service.import_tasks(
        uow=uow,
        payload=payload.payload,
        team_id=team_id,
        provider=provider,
        clients=getattr(request.app.state, "data_clients", None),
    )
    return TaskImportResult(
        provider=provider,
        imported=len(imported),
        tasks=imported,
    )
