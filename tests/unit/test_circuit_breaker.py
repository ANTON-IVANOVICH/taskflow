import pytest

from app.integrations.circuit_breaker import (
    CLOSED,
    HALF_OPEN,
    OPEN,
    CircuitBreaker,
    CircuitBreakerError,
)

pytestmark = pytest.mark.unit


def test_circuit_breaker_opens_after_threshold_and_recovers() -> None:
    breaker = CircuitBreaker(name="payments", threshold=2, reset_seconds=10)

    breaker.record_failure()
    assert breaker.state == CLOSED
    breaker.record_failure()
    assert breaker.state == OPEN

    with pytest.raises(CircuitBreakerError):
        breaker.before_request()

    breaker._opened_at -= 11
    breaker.before_request()
    assert breaker.state == HALF_OPEN
    breaker.record_success()
    assert breaker.state == CLOSED


def test_circuit_breaker_success_resets_consecutive_failures() -> None:
    breaker = CircuitBreaker(name="search", threshold=3, reset_seconds=10)

    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()

    assert breaker.state == CLOSED
