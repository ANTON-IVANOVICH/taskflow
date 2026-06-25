"""In-process WebSocket connection registry with room-based broadcast.

One instance per process. For multi-instance fan-out, a :class:`~app.websockets.broker.EventBroker`
sits in front and re-broadcasts cross-instance messages into each process's manager.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from starlette.websockets import WebSocket

logger = logging.getLogger("taskflow.ws")


class ConnectionManager:
    def __init__(self, *, send_timeout_seconds: float = 5.0) -> None:
        self._rooms: dict[str, set[tuple[WebSocket, int]]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._send_timeout = send_timeout_seconds

    @property
    def active_connections(self) -> int:
        return sum(len(members) for members in self._rooms.values())

    @property
    def active_rooms(self) -> int:
        return len(self._rooms)

    async def connect(self, room: str, websocket: WebSocket, user_id: int) -> None:
        async with self._lock:
            self._rooms[room].add((websocket, user_id))

    async def disconnect(self, room: str, websocket: WebSocket, user_id: int) -> None:
        async with self._lock:
            members = self._rooms.get(room)
            if members is None:
                return
            members.discard((websocket, user_id))
            if not members:
                del self._rooms[room]

    async def broadcast(
        self,
        room: str,
        message: dict[str, Any],
        *,
        exclude_user: int | None = None,
    ) -> int:
        # Snapshot under lock so a disconnect mid-broadcast can't mutate the set we iterate.
        async with self._lock:
            members = list(self._rooms.get(room, set()))

        delivered = 0
        dead: list[tuple[WebSocket, int]] = []
        for websocket, user_id in members:
            if exclude_user is not None and user_id == exclude_user:
                continue
            try:
                await asyncio.wait_for(
                    websocket.send_json(message),
                    timeout=self._send_timeout,
                )
                delivered += 1
            except Exception:  # noqa: BLE001 - slow/broken client: drop it, keep broadcasting
                dead.append((websocket, user_id))

        for websocket, user_id in dead:
            await self.disconnect(room, websocket, user_id)
        return delivered
