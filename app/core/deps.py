from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Query, Security
from fastapi.security import SecurityScopes
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDenied, UnauthorizedError
from app.core.security import api_key_scheme, oauth2_scheme, resolve_api_key
from app.db.bootstrap import ensure_schema_initialized
from app.db.session import async_session_maker
from app.db.uow import SqlAlchemyUnitOfWork
from app.schemas.users import UserRead
from app.services.users import build_m2m_user, decode_access_token


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    await ensure_schema_initialized()
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


DBSession = Annotated[AsyncSession, Depends(get_db)]


async def get_uow(db: DBSession) -> AsyncGenerator[SqlAlchemyUnitOfWork, None]:
    uow = SqlAlchemyUnitOfWork(session=db)
    try:
        yield uow
    except Exception:
        await uow.rollback()
        raise


UoWDep = Annotated[SqlAlchemyUnitOfWork, Depends(get_uow)]


class Paginator:
    def __init__(
        self,
        limit: Annotated[int, Query(description="Page size", ge=1, le=100)] = 20,
        offset: Annotated[int, Query(description="Offset", ge=0)] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


async def get_current_user(
    security_scopes: SecurityScopes,
    token: Annotated[str | None, Depends(oauth2_scheme)],
    api_key: Annotated[str | None, Security(api_key_scheme)],
) -> UserRead:
    user: UserRead
    if token is not None:
        user = decode_access_token(token)
    else:
        api_principal = resolve_api_key(api_key)
        if api_principal is None:
            raise UnauthorizedError("Missing authentication credentials")
        user = build_m2m_user(scopes=api_principal.scopes, key_id=api_principal.key_id)

    missing_scopes = [scope for scope in security_scopes.scopes if scope not in user.scopes]
    if missing_scopes:
        missing = ", ".join(missing_scopes)
        raise PermissionDenied(f"Missing required scopes: {missing}")
    return user


CurrentUser = Annotated[UserRead, Security(get_current_user)]
AdminUser = Annotated[UserRead, Security(get_current_user, scopes=["admin"])]
TasksReader = Annotated[UserRead, Security(get_current_user, scopes=["tasks:read"])]
TasksWriter = Annotated[UserRead, Security(get_current_user, scopes=["tasks:write"])]
TeamsReader = Annotated[UserRead, Security(get_current_user, scopes=["teams:read"])]
IntegrationsWriter = Annotated[UserRead, Security(get_current_user, scopes=["integrations:write"])]
