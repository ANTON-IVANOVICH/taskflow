"""LLM streaming via the Anthropic Messages API (raw async httpx).

The whole point of Layer 5 is resilient raw-HTTP integration, so this calls
``POST {base_url}/v1/messages`` with ``"stream": true`` directly and parses the SSE event stream,
rather than pulling in the ``anthropic`` SDK. A semaphore caps concurrent calls (provider quota),
and when no API key is configured it degrades to a deterministic offline echo so the endpoint —
and its tests — work without network or credentials.

Default model: ``claude-opus-4-8``. Anthropic SSE deltas arrive as ``content_block_delta`` events
whose ``delta.type == "text_delta"`` carries incremental ``delta.text``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Sequence

import httpx

from app.core.errors import UpstreamError

logger = logging.getLogger("taskflow.integrations")


def parse_sse_text_delta(data: str) -> str | None:
    """Extract incremental text from one Anthropic SSE ``data:`` payload, or None."""

    try:
        event = json.loads(data)
    except json.JSONDecodeError:
        return None
    if event.get("type") != "content_block_delta":
        return None
    delta = event.get("delta") or {}
    if delta.get("type") == "text_delta":
        text = delta.get("text")
        return text if isinstance(text, str) else None
    return None


class LLMService:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        api_key: str | None,
        base_url: str,
        model: str,
        version: str,
        max_tokens: int,
        max_concurrency: int,
        timeout_seconds: float,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._version = version
        self._max_tokens = max_tokens
        self._timeout = timeout_seconds
        self._sem = asyncio.Semaphore(max_concurrency)

    @property
    def live(self) -> bool:
        return self._api_key is not None

    @property
    def model(self) -> str:
        return self._model if self.live else "offline-fallback"

    async def stream(
        self,
        messages: Sequence[dict[str, object]],
        *,
        system: str | None = None,
    ) -> AsyncIterator[str]:
        async with self._sem:
            if not self.live:
                async for chunk in self._fallback_stream(messages):
                    yield chunk
                return
            async for chunk in self._anthropic_stream(messages, system):
                yield chunk

    async def _anthropic_stream(
        self,
        messages: Sequence[dict[str, object]],
        system: str | None,
    ) -> AsyncIterator[str]:
        body: dict[str, object] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": list(messages),
            "stream": True,
        }
        if system:
            body["system"] = system
        headers = {
            "x-api-key": self._api_key or "",
            "anthropic-version": self._version,
            "content-type": "application/json",
        }
        try:
            async with self._client.stream(
                "POST",
                f"{self._base_url}/v1/messages",
                headers=headers,
                json=body,
                timeout=self._timeout,
            ) as response:
                if response.status_code != 200:
                    detail = (await response.aread()).decode(errors="replace")[:500]
                    raise UpstreamError(f"LLM provider returned {response.status_code}: {detail}")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    text = parse_sse_text_delta(line[len("data:") :].strip())
                    if text:
                        yield text
        except httpx.HTTPError as exc:
            logger.warning("llm_stream_failed", extra={"error": str(exc)})
            raise UpstreamError("Failed to reach LLM provider") from exc

    async def _fallback_stream(
        self,
        messages: Sequence[dict[str, object]],
    ) -> AsyncIterator[str]:
        prompt = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                content = message.get("content")
                if isinstance(content, str):
                    prompt = content
                break
        reply = f"[offline] TaskFlow assistant received: {prompt}".strip()
        for word in reply.split(" "):
            await asyncio.sleep(0)
            yield word + " "
