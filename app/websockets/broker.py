"""Cross-instance event fan-out over Redis Pub/Sub.

With several app processes behind a load balancer, WebSocket clients for the same room land on
different processes. The in-memory :class:`ConnectionManager` only sees local sockets, so a local
broadcast misses remote clients. This broker publishes every event to Redis; each process runs a
listener that re-broadcasts incoming messages into its own manager. When Redis is absent the broker
is simply not created and callers fall back to a local broadcast.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.websockets.manager import ConnectionManager

logger = logging.getLogger("taskflow.ws")


class EventBroker:
    def __init__(
        self,
        *,
        redis: Any,
        manager: ConnectionManager,
        channel_prefix: str = "taskflow:rt",
    ) -> None:
        self._redis = redis
        self._manager = manager
        self._channel_prefix = channel_prefix
        self._pubsub: Any | None = None
        self._listener: asyncio.Task[None] | None = None

    def _channel(self, room: str) -> str:
        return f"{self._channel_prefix}:{room}"

    async def publish(self, room: str, message: dict[str, Any]) -> None:
        payload = json.dumps({"room": room, "message": message}, ensure_ascii=False)
        await self._redis.publish(self._channel(room), payload)

    async def start(self) -> None:
        self._pubsub = self._redis.pubsub()
        await self._pubsub.psubscribe(f"{self._channel_prefix}:*")
        self._listener = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            try:
                await self._listener
            except asyncio.CancelledError:
                pass
        if self._pubsub is not None:
            await self._pubsub.aclose()

    async def _listen(self) -> None:
        assert self._pubsub is not None
        async for raw in self._pubsub.listen():
            if raw.get("type") != "pmessage":
                continue
            try:
                envelope = json.loads(raw["data"])
                await self._manager.broadcast(envelope["room"], envelope["message"])
            except Exception:  # noqa: BLE001 - one bad frame must not kill the listener
                logger.warning("ws_broker_bad_message")
