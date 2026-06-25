"""Helpers for running independent IO/CPU work concurrently inside a request.

``async def`` only yields the event loop on ``await`` — it does not parallelize CPU work
and it does not make sequential awaits run together. These helpers make the two common
needs explicit: fan out independent coroutines, and push blocking/CPU work off the loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


async def gather_mapping(coros: Mapping[str, Awaitable[T]]) -> dict[str, T]:
    """Run named coroutines concurrently and return a dict keyed by the same names.

    Any exception propagates (fail-fast), mirroring ``asyncio.gather`` defaults.
    """

    keys = list(coros.keys())
    results = await asyncio.gather(*(coros[key] for key in keys))
    return dict(zip(keys, results, strict=True))


async def bounded_gather(
    factories: list[Callable[[], Awaitable[T]]],
    *,
    limit: int,
) -> list[T]:
    """Run coroutine factories concurrently, but at most ``limit`` at a time.

    Takes zero-arg factories rather than coroutines so nothing starts before a slot is
    free (useful for rate-limited external APIs). Order of results matches input order.
    """

    if limit < 1:
        raise ValueError("limit must be >= 1")
    semaphore = asyncio.Semaphore(limit)

    async def _run(factory: Callable[[], Awaitable[T]]) -> T:
        async with semaphore:
            return await factory()

    return list(await asyncio.gather(*(_run(factory) for factory in factories)))


async def run_cpu_bound(func: Callable[..., R], /, *args: object) -> R:
    """Offload a blocking/CPU-bound callable to a worker thread off the event loop."""

    return await asyncio.to_thread(func, *args)
