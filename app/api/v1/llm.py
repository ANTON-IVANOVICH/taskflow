from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Body, Request
from fastapi.responses import StreamingResponse

from app.core.deps import TasksReader
from app.core.errors import UpstreamError
from app.integrations.runtime import get_llm_service
from app.schemas.llm import ChatRequest

router = APIRouter(prefix="/llm", tags=["llm"])


@router.post(
    "/chat/stream",
    summary="Stream an LLM chat completion as Server-Sent Events",
)
async def chat_stream(
    payload: Annotated[ChatRequest, Body()],
    current_user: TasksReader,
    request: Request,
) -> StreamingResponse:
    del current_user
    llm = get_llm_service(request.app)
    messages: list[dict[str, object]] = [
        {"role": message.role, "content": message.content} for message in payload.messages
    ]

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            async for delta in llm.stream(messages, system=payload.system):
                data = json.dumps({"text": delta}, ensure_ascii=False)
                yield f"event: delta\ndata: {data}\n\n"
            yield "event: done\ndata: {}\n\n"
        except UpstreamError as exc:
            data = json.dumps({"error": exc.message}, ensure_ascii=False)
            yield f"event: error\ndata: {data}\n\n"

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)
