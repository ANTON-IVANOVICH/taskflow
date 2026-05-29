from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.config import get_settings
from app.core.deps import CurrentUser, DBSession
from app.schemas.users import TokenOut, UserRead, UserRegister
from app.services import users as user_service

router = APIRouter(prefix="/users", tags=["users"])
settings = get_settings()


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(
    payload: Annotated[UserRegister, Body()],
    background_tasks: BackgroundTasks,
    db: DBSession,
) -> UserRead:
    del db
    user = user_service.register_user(payload)
    background_tasks.add_task(user_service.send_welcome_email, user.email, user.name)
    return user


@router.post("/token", response_model=TokenOut, summary="Issue OAuth2 password token")
async def login_for_access_token(
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    user_agent: Annotated[str | None, Header(alias="User-Agent")] = None,
    device_id: Annotated[str | None, Header(alias="X-Device-Id")] = None,
) -> TokenOut:
    scopes = form_data.scopes
    token_out = user_service.authenticate(
        form_data.username,
        form_data.password,
        scopes,
        user_agent=user_agent,
        device_id=device_id,
    )
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token_out.refresh_token,
        httponly=True,
        samesite="lax",
        secure=settings.app_env != "local",
        path="/",
    )
    if settings.csrf_enabled and token_out.csrf_token is not None:
        response.set_cookie(
            key=settings.csrf_cookie_name,
            value=token_out.csrf_token,
            httponly=False,
            samesite="lax",
            secure=settings.app_env != "local",
            path="/",
        )
    return token_out


@router.get("/me", response_model=UserRead, summary="Current authenticated user")
async def read_me(current_user: CurrentUser, db: DBSession) -> UserRead:
    del db
    return current_user


@router.get(
    "/internal/all",
    response_model=list[UserRead],
    include_in_schema=False,
    summary="Hidden internal route",
)
async def list_all_users() -> list[UserRead]:
    return user_service.list_users()
