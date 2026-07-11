"""A minimal in-memory circuit breaker.

If a downstream service fails repeatedly, hammering it with retries only deepens the outage and
ties up our own connection pool. The breaker trips ``open`` after N consecutive failures and
fails fast for a cooldown window, then allows a single ``half-open`` probe to test recovery.
"""

from __future__ import annotations

import time

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


class CircuitBreakerError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"Circuit breaker '{name}' is open")
        self.name = name


class CircuitBreaker:
    def __init__(self, *, name: str, threshold: int = 5, reset_seconds: float = 30.0) -> None:
        self.name = name
        self._threshold = threshold
        self._reset_seconds = reset_seconds
        self._failures = 0
        self._state = CLOSED
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        return self._state

    def _now(self) -> float:
        return time.monotonic()

    def before_request(self) -> None:
        """Raise if the circuit is open; transition to half-open once the cooldown elapses."""

        if self._state == OPEN:
            if self._now() - self._opened_at >= self._reset_seconds:
                self._state = HALF_OPEN
            else:
                raise CircuitBreakerError(self.name)

    def record_success(self) -> None:
        self._failures = 0
        self._state = CLOSED

    def record_failure(self) -> None:
        self._failures += 1
        if self._state == HALF_OPEN or self._failures >= self._threshold:
            self._state = OPEN
            self._opened_at = self._now()
