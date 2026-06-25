from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.errors import DomainError
from app.websockets.realtime import authenticate_ws, connection_manager, task_room

router = APIRouter(prefix="/ws", tags=["realtime"])

WS_POLICY_VIOLATION = 1008


@router.websocket("/tasks/{task_id}")
async def task_updates(
    websocket: WebSocket,
    task_id: int,
    token: Annotated[str | None, Query(description="Access token (browsers can't set headers)")] = (
        None
    ),
) -> None:
    """Live task room: authenticate before accept, then relay pings and broadcasts.

    Clients receive ``task_event`` pushes emitted when the task is updated over REST, and may
    send ``{"type": "ping"}`` (-> ``pong``) or ``{"type": "broadcast", "text": ...}`` (fanned
    out to everyone else in the room).
    """

    try:
        user = authenticate_ws(token, required_scope="tasks:read")
    except DomainError as exc:
        await websocket.close(code=WS_POLICY_VIOLATION, reason=exc.code)
        return

    await websocket.accept()
    room = task_room(task_id)
    await connection_manager.connect(room, websocket, user.id)
    try:
        await websocket.send_json({"type": "connected", "task_id": task_id})
        while True:
            data = await websocket.receive_json()
            message_type = data.get("type")
            if message_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif message_type == "broadcast":
                await connection_manager.broadcast(
                    room,
                    {"type": "message", "from": user.id, "text": data.get("text", "")},
                    exclude_user=user.id,
                )
            else:
                await websocket.send_json({"type": "error", "detail": "unknown message type"})
    except WebSocketDisconnect:
        pass
    finally:
        await connection_manager.disconnect(room, websocket, user.id)
        if websocket.client_state != WebSocketState.DISCONNECTED:
            await websocket.close()
