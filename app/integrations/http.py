"""A resilient async HTTP client wrapper for talking to flaky external services.

Adds three things on top of a shared ``httpx.AsyncClient``: retry with exponential backoff + jitter
(only for retryable errors and safe/idempotent requests), ``Retry-After`` honouring, and a
per-service circuit breaker. One long-lived ``httpx.AsyncClient`` is reused for keep-alive.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.integrations.circuit_breaker import CircuitBreaker

logger = logging.getLogger("taskflow.integrations")

# Network errors worth retrying — transient, not a signal the request itself is bad.
RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})


@dataclass
class RetryPolicy:
    attempts: int = 3
    base_delay: float = 0.2
    max_delay: float = 10.0
    max_after: float = 30.0

    def backoff(self, attempt: int) -> float:
        # Exponential backoff with full jitter — jitter avoids synchronized retry storms.
        ceiling = min(self.max_delay, self.base_delay * (2**attempt))
        return random.uniform(0, ceiling) if ceiling > 0 else 0.0


def create_http_client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=settings.http_connect_timeout,
            read=settings.http_read_timeout,
            write=settings.http_write_timeout,
            pool=settings.http_pool_timeout,
        ),
        limits=httpx.Limits(
            max_connections=settings.http_max_connections,
            max_keepalive_connections=settings.http_max_keepalive,
        ),
        follow_redirects=False,
        headers={"User-Agent": "TaskFlow/1.0"},
    )


class ResilientHttpClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        retry: RetryPolicy | None = None,
        breaker_threshold: int = 5,
        breaker_reset_seconds: float = 30.0,
    ) -> None:
        self._client = client
        self._retry = retry or RetryPolicy()
        self._breaker_threshold = breaker_threshold
        self._breaker_reset_seconds = breaker_reset_seconds
        self._breakers: dict[str, CircuitBreaker] = {}

    def breaker(self, name: str) -> CircuitBreaker:
        breaker = self._breakers.get(name)
        if breaker is None:
            breaker = CircuitBreaker(
                name=name,
                threshold=self._breaker_threshold,
                reset_seconds=self._breaker_reset_seconds,
            )
            self._breakers[name] = breaker
        return breaker

    async def _sleep(self, delay: float) -> None:
        if delay > 0:
            await asyncio.sleep(delay)

    def _retry_after(self, response: httpx.Response) -> float | None:
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return min(float(raw), self._retry.max_after)
        except ValueError:
            return None  # HTTP-date form — fall back to computed backoff

    async def request(
        self,
        method: str,
        url: str,
        *,
        idempotency_key: str | None = None,
        breaker_name: str | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        method = method.upper()
        breaker = self.breaker(breaker_name) if breaker_name else None
        if breaker is not None:
            breaker.before_request()  # fail fast if the circuit is open

        raw_headers = kwargs.pop("headers", None)
        headers: dict[str, str] = {}
        if isinstance(raw_headers, Mapping):
            headers = {str(key): str(value) for key, value in raw_headers.items()}
        if idempotency_key is not None:
            headers.setdefault("Idempotency-Key", idempotency_key)
        retryable_request = method in SAFE_METHODS or idempotency_key is not None

        response: httpx.Response | None = None
        for attempt in range(self._retry.attempts):
            last_attempt = attempt + 1 >= self._retry.attempts
            try:
                response = await self._client.request(method, url, headers=headers, **kwargs)  # type: ignore[arg-type]
            except RETRYABLE_EXCEPTIONS as exc:
                if last_attempt:
                    if breaker is not None:
                        breaker.record_failure()
                    raise
                logger.warning(
                    "http_retry",
                    extra={"url": url, "attempt": attempt, "error": str(exc)},
                )
                await self._sleep(self._retry.backoff(attempt))
                continue

            if (
                response.status_code in RETRYABLE_STATUS
                and retryable_request
                and not last_attempt
            ):
                delay = self._retry_after(response)
                await self._sleep(delay if delay is not None else self._retry.backoff(attempt))
                continue

            if breaker is not None:
                if response.status_code >= 500:
                    breaker.record_failure()
                else:
                    breaker.record_success()
            return response

        # Retries exhausted on a retryable status — record failure and return the last response.
        assert response is not None
        if breaker is not None:
            breaker.record_failure()
        return response
