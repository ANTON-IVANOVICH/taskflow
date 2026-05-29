from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", summary="Readiness probe")
async def ready() -> dict[str, str]:
    return {"status": "ready"}
