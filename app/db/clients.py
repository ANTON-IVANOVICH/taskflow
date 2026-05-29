from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.db.search import MeiliSearchGateway
from app.schemas.tasks import TaskEventRead


@dataclass
class DataClients:
    redis_client: Any | None = None
    mongo_client: Any | None = None
    mongo_collection: Any | None = None
    search_gateway: MeiliSearchGateway | None = None


async def init_data_clients(http_client: httpx.AsyncClient) -> DataClients:
    settings = get_settings()
    clients = DataClients()

    if settings.redis_url:
        try:
            import redis.asyncio as redis

            redis_client = redis.from_url(settings.redis_url, decode_responses=True)
            await redis_client.ping()
            clients.redis_client = redis_client
        except Exception:  # noqa: BLE001
            clients.redis_client = None

    if settings.mongo_url:
        try:
            from motor.motor_asyncio import AsyncIOMotorClient

            mongo_client = AsyncIOMotorClient(settings.mongo_url)
            await mongo_client.admin.command("ping")
            clients.mongo_client = mongo_client
            clients.mongo_collection = mongo_client[settings.mongo_db_name][
                settings.mongo_events_collection
            ]
        except Exception:  # noqa: BLE001
            if clients.mongo_client is not None:
                clients.mongo_client.close()
            clients.mongo_client = None
            clients.mongo_collection = None

    if settings.meilisearch_url:
        clients.search_gateway = MeiliSearchGateway(
            client=http_client,
            base_url=settings.meilisearch_url,
            api_key=settings.meilisearch_api_key,
            index_uid=settings.meilisearch_index,
        )

    return clients


async def close_data_clients(clients: DataClients) -> None:
    redis_client = clients.redis_client
    if redis_client is not None:
        close_method = getattr(redis_client, "aclose", None) or getattr(redis_client, "close", None)
        if close_method is not None:
            result = close_method()
            if hasattr(result, "__await__"):
                await result

    mongo_client = clients.mongo_client
    if mongo_client is not None:
        mongo_client.close()


async def publish_task_event(clients: DataClients, event: TaskEventRead) -> None:
    payload = event.model_dump(mode="json")

    if clients.redis_client is not None:
        key = f"task:{event.task_id}:events"
        serialized = json.dumps(payload, ensure_ascii=False)
        await clients.redis_client.lpush(key, serialized)
        await clients.redis_client.ltrim(key, 0, 199)
        await clients.redis_client.expire(key, 3600)

    if clients.mongo_collection is not None:
        await clients.mongo_collection.insert_one(payload)
