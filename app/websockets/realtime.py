"""Process-wide real-time singletons and helpers shared by routers and lifespan.

The connection manager is a module-level singleton (not on ``app.state``) so it works in tests,
where the app lifespan does not run. ``broadcast_task_event`` prefers the cross-instance broker
when one was wired up at startup and otherwise broadcasts to local sockets directly.
"""

from __future__ import annotations

from typing import Any

from starlette.websockets import WebSocket

from app.core.config import get_settings
from app.core.errors import PermissionDenied, UnauthorizedError
from app.schemas.users import UserRead
from app.services.users import decode_access_token
from app.websockets.manager import ConnectionManager

_settings = get_settings()
connection_manager = ConnectionManager(send_timeout_seconds=_settings.ws_send_timeout_seconds)


def authenticate_ws(token: str | None, *, required_scope: str) -> UserRead:
    """Authenticate a WebSocket from its query-param token before ``accept``.

    Browsers can't set ``Authorization`` on the WebSocket handshake, so the access token is
    passed as ``?token=``. Rejecting before accept avoids leaking half-open connections.
    """

    if not token:
        raise UnauthorizedError("Missing WebSocket token")
    user = decode_access_token(token)
    if required_scope not in user.scopes:
        raise PermissionDenied(f"Missing required scope: {required_scope}")
    return user


def task_room(task_id: int) -> str:
    return f"task:{task_id}"


async def broadcast_task_event(app: Any, room: str, message: dict[str, Any]) -> None:
    """Fan a real-time message out cross-instance via the broker, or locally if there's none."""

    broker = getattr(app.state, "event_broker", None)
    if broker is not None:
        await broker.publish(room, message)
        return
    await connection_manager.broadcast(room, message)


async def reject_websocket(websocket: WebSocket, *, code: int, reason: str) -> None:
    await websocket.close(code=code, reason=reason)
