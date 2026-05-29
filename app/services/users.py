from __future__ import annotations

import asyncio
import secrets
from collections.abc import Iterable
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.errors import PermissionDenied, UnauthorizedError, UserAlreadyExists
from app.core.security import (
    create_access_token,
    create_csrf_token,
    create_refresh_token,
    decode_refresh_token,
    now_utc_ts,
)
from app.core.security import (
    decode_access_token as decode_access_jwt,
)
from app.schemas.users import TokenOut, UserRead, UserRegister

_USERS: dict[int, UserRead] = {
    1: UserRead(
        id=1,
        email="admin@taskflow.dev",
        name="Admin",
        is_admin=True,
        scopes=["tasks:read", "tasks:write", "teams:read", "integrations:write", "admin"],
    )
}
_PASSWORDS: dict[str, str] = {
    "admin@taskflow.dev": "admin12345",
}


@dataclass
class RefreshSession:
    user_id: int
    session_id: str
    scopes: list[str]
    user_agent: str | None
    device_id: str | None
    csrf_token: str
    expires_at: int


_REFRESH_SESSIONS: dict[str, RefreshSession] = {}


def _next_user_id() -> int:
    return max(_USERS.keys(), default=0) + 1


def list_users() -> list[UserRead]:
    return list(_USERS.values())


def register_user(payload: UserRegister) -> UserRead:
    if any(user.email == payload.email for user in _USERS.values()):
        raise UserAlreadyExists(payload.email)

    user = UserRead(
        id=_next_user_id(),
        email=payload.email,
        name=payload.name,
        is_admin=False,
        scopes=["tasks:read", "teams:read"],
    )
    _USERS[user.id] = user
    _PASSWORDS[user.email] = payload.password
    return user


def authenticate(
    email: str,
    password: str,
    requested_scopes: Iterable[str] | None = None,
    user_agent: str | None = None,
    device_id: str | None = None,
) -> TokenOut:
    user = next((u for u in _USERS.values() if u.email == email), None)
    if user is None:
        raise UnauthorizedError("Invalid credentials")

    expected_password = _PASSWORDS.get(user.email)
    if expected_password != password:
        raise UnauthorizedError("Invalid credentials")

    requested = list(requested_scopes or user.scopes)
    unauthorized_scopes = [scope for scope in requested if scope not in user.scopes]
    if unauthorized_scopes:
        denied = ", ".join(unauthorized_scopes)
        raise PermissionDenied(f"Requested scopes are not allowed: {denied}")

    return _issue_token_pair(
        user=user,
        scopes=requested,
        user_agent=user_agent,
        device_id=device_id,
    )


def authenticate_oauth_identity(
    *,
    email: str,
    name: str | None,
    user_agent: str | None = None,
    device_id: str | None = None,
) -> TokenOut:
    user = next((u for u in _USERS.values() if u.email == email), None)
    if user is None:
        user = UserRead(
            id=_next_user_id(),
            email=email,
            name=name or email,
            is_admin=False,
            scopes=["tasks:read", "teams:read"],
        )
        _USERS[user.id] = user
        # OAuth users do not have a local password until explicitly set.
        _PASSWORDS.setdefault(email, "")

    return _issue_token_pair(
        user=user,
        scopes=user.scopes,
        user_agent=user_agent,
        device_id=device_id,
    )


def decode_access_token(token: str) -> UserRead:
    payload = decode_access_jwt(token)
    user_id = payload.get("uid")
    if not isinstance(user_id, int):
        raise UnauthorizedError("Invalid token subject")

    user = _USERS.get(user_id)
    if user is None:
        raise UnauthorizedError("Unknown user")

    scopes_raw = payload.get("scope")
    scopes = scopes_raw.split() if isinstance(scopes_raw, str) else []
    token_admin = bool(payload.get("is_admin", user.is_admin))
    return user.model_copy(update={"scopes": scopes, "is_admin": token_admin})


def build_m2m_user(scopes: set[str], key_id: str) -> UserRead:
    return UserRead(
        id=0,
        email=f"m2m-{key_id}@taskflow.dev",
        name=f"m2m:{key_id}",
        is_admin=False,
        scopes=sorted(scopes),
    )


def refresh_access_token(
    refresh_token: str,
    user_agent: str,
    device_id: str,
    csrf_token: str | None,
) -> TokenOut:
    payload = decode_refresh_token(refresh_token)
    session = _REFRESH_SESSIONS.get(refresh_token)
    if session is None:
        raise UnauthorizedError("Invalid refresh token")

    if now_utc_ts() >= session.expires_at:
        _REFRESH_SESSIONS.pop(refresh_token, None)
        raise UnauthorizedError("Refresh token expired")

    token_user_id = payload.get("uid")
    token_session_id = payload.get("sid")
    if token_user_id != session.user_id or token_session_id != session.session_id:
        raise UnauthorizedError("Refresh session mismatch")

    if session.user_agent and session.user_agent != user_agent:
        raise UnauthorizedError("User-Agent mismatch for refresh session")
    if session.device_id and session.device_id != device_id:
        raise UnauthorizedError("Device mismatch for refresh session")

    settings = get_settings()
    if settings.csrf_enabled and csrf_token != session.csrf_token:
        raise UnauthorizedError("CSRF token mismatch")

    user = _USERS.get(session.user_id)
    if user is None:
        raise UnauthorizedError("Unknown user")

    _REFRESH_SESSIONS.pop(refresh_token, None)
    return _issue_token_pair(
        user=user,
        scopes=session.scopes,
        user_agent=user_agent,
        device_id=device_id,
    )


def _issue_token_pair(
    *,
    user: UserRead,
    scopes: list[str],
    user_agent: str | None,
    device_id: str | None,
) -> TokenOut:
    settings = get_settings()
    session_id = secrets.token_urlsafe(16)
    access_token, access_ttl = create_access_token(
        user_id=user.id,
        scopes=scopes,
        is_admin=user.is_admin,
        subject=user.email,
    )
    refresh_token, refresh_ttl = create_refresh_token(
        user_id=user.id,
        subject=user.email,
        session_id=session_id,
    )
    csrf_token = create_csrf_token()
    _REFRESH_SESSIONS[refresh_token] = RefreshSession(
        user_id=user.id,
        session_id=session_id,
        scopes=scopes,
        user_agent=user_agent,
        device_id=device_id,
        csrf_token=csrf_token,
        expires_at=now_utc_ts() + refresh_ttl,
    )
    return TokenOut(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=access_ttl,
        refresh_expires_in=refresh_ttl,
        csrf_token=csrf_token if settings.csrf_enabled else None,
    )


async def send_welcome_email(email: str, name: str) -> None:
    await asyncio.sleep(0.01)
    print(f"[background] welcome email queued to {email} for {name}")
