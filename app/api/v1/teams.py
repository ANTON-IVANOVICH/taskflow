from fastapi import APIRouter, Depends, status

from app.core.deps import AdminUser, TeamsReader, UoWDep
from app.core.security import require_api_key
from app.schemas.teams import TeamCreate, TeamRead
from app.services import teams as team_service

router = APIRouter(
    prefix="/teams",
    tags=["teams"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/", response_model=list[TeamRead], summary="List teams")
async def list_teams(current_user: TeamsReader, uow: UoWDep) -> list[TeamRead]:
    del current_user
    return await team_service.list_teams(uow=uow)


@router.post(
    "/",
    response_model=TeamRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create team",
)
async def create_team(payload: TeamCreate, current_user: AdminUser, uow: UoWDep) -> TeamRead:
    del current_user
    return await team_service.create_team(uow=uow, payload=payload)
