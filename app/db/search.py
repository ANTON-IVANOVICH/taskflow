from __future__ import annotations

from typing import Any

import httpx


class MeiliSearchGateway:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        base_url: str,
        index_uid: str,
        api_key: str | None = None,
    ) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.index_uid = index_uid
        self.api_key = api_key

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.index_uid)

    async def search_task_ids(
        self,
        query: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> set[int] | None:
        if not self.enabled or not query.strip():
            return None

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = await self.client.post(
                f"{self.base_url}/indexes/{self.index_uid}/search",
                json={"q": query, "limit": limit, "offset": offset},
                headers=headers,
            )
            response.raise_for_status()
        except Exception:  # noqa: BLE001
            return None

        body = response.json()
        hits = body.get("hits")
        if not isinstance(hits, list):
            return None

        result: set[int] = set()
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            raw_id: Any = hit.get("id")
            if isinstance(raw_id, int):
                result.add(raw_id)
                continue
            if isinstance(raw_id, str) and raw_id.isdigit():
                result.add(int(raw_id))
        return result
