"""Wiring for the integrations layer: default resilient HTTP client + LLM service.

Like the worker/storage layers, these are module-level singletons used when the app lifespan
never runs (tests, imports). The lifespan builds fresh instances on ``app.state`` sharing the
long-lived ``httpx.AsyncClient``; the ``get_*`` helpers prefer those and fall back to the defaults.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings
from app.integrations.email import EmailService
from app.integrations.http import ResilientHttpClient, RetryPolicy, create_http_client
from app.integrations.llm import LLMService
from app.integrations.stripe import StripeService

_settings = get_settings()
_default_http: httpx.AsyncClient = create_http_client()

default_resilient_client = ResilientHttpClient(
    _default_http,
    retry=RetryPolicy(
        attempts=_settings.http_retry_attempts,
        base_delay=_settings.http_retry_base_delay,
        max_delay=_settings.http_retry_max_delay,
        max_after=_settings.http_retry_max_after,
    ),
    breaker_threshold=_settings.circuit_breaker_threshold,
    breaker_reset_seconds=_settings.circuit_breaker_reset_seconds,
)


def build_resilient_client(client: httpx.AsyncClient) -> ResilientHttpClient:
    settings = get_settings()
    return ResilientHttpClient(
        client,
        retry=RetryPolicy(
            attempts=settings.http_retry_attempts,
            base_delay=settings.http_retry_base_delay,
            max_delay=settings.http_retry_max_delay,
            max_after=settings.http_retry_max_after,
        ),
        breaker_threshold=settings.circuit_breaker_threshold,
        breaker_reset_seconds=settings.circuit_breaker_reset_seconds,
    )


def build_llm_service(client: httpx.AsyncClient) -> LLMService:
    settings = get_settings()
    return LLMService(
        client=client,
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url,
        model=settings.anthropic_model,
        version=settings.anthropic_version,
        max_tokens=settings.llm_max_tokens,
        max_concurrency=settings.llm_max_concurrency,
        timeout_seconds=settings.llm_timeout_seconds,
    )


default_llm_service = build_llm_service(_default_http)


def build_email_service(client: ResilientHttpClient) -> EmailService:
    settings = get_settings()
    return EmailService(
        client=client,
        provider=settings.email_provider,
        base_url=settings.email_provider_base_url,
        api_key=settings.email_api_key,
        from_address=settings.email_from,
        timeout_seconds=settings.email_timeout_seconds,
    )


def build_stripe_service(client: ResilientHttpClient) -> StripeService:
    settings = get_settings()
    return StripeService(
        client=client,
        api_key=settings.stripe_api_key,
        base_url=settings.stripe_base_url,
        timeout_seconds=settings.stripe_timeout_seconds,
    )


default_email_service = build_email_service(default_resilient_client)
default_stripe_service = build_stripe_service(default_resilient_client)


def get_resilient_client(app: Any) -> ResilientHttpClient:
    client = getattr(app.state, "resilient_client", None)
    if isinstance(client, ResilientHttpClient):
        return client
    return default_resilient_client


def get_llm_service(app: Any) -> LLMService:
    service = getattr(app.state, "llm_service", None)
    if isinstance(service, LLMService):
        return service
    return default_llm_service


def get_email_service(app: Any) -> EmailService:
    service = getattr(app.state, "email_service", None)
    if isinstance(service, EmailService):
        return service
    return default_email_service


def get_stripe_service(app: Any) -> StripeService:
    service = getattr(app.state, "stripe_service", None)
    if isinstance(service, StripeService):
        return service
    return default_stripe_service
