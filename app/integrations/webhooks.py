"""Webhook signing and verification.

Inbound: verify the provider's signature over the raw body before trusting anything — Stripe uses a
``t=<ts>,v1=<hmac>`` scheme, GitHub/generic use ``sha256=<hmac>``. Outbound: sign our own payloads
so subscribers can verify us the same way.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from collections.abc import Mapping
from functools import lru_cache

from app.core.config import get_settings
from app.core.errors import InvalidSignature


@lru_cache
def _secrets() -> dict[str, str]:
    raw = get_settings().webhook_signing_secrets
    secrets: dict[str, str] = {}
    for pair in raw.split(";"):
        pair = pair.strip()
        if not pair:
            continue
        provider, sep, secret = pair.partition("=")
        if sep and provider.strip():
            secrets[provider.strip()] = secret.strip()
    return secrets


def _hex_hmac(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def sign_payload(secret: str, body: bytes) -> str:
    """Signature for outbound webhooks; subscribers verify with the shared secret."""

    return f"sha256={_hex_hmac(secret, body)}"


def _verify_generic(secret: str, body: bytes, signature_header: str | None) -> None:
    if not signature_header:
        raise InvalidSignature("Missing webhook signature header")
    provided = signature_header.removeprefix("sha256=")
    expected = _hex_hmac(secret, body)
    if not hmac.compare_digest(provided, expected):
        raise InvalidSignature("Webhook signature mismatch")


def _verify_stripe(
    secret: str,
    body: bytes,
    signature_header: str | None,
    tolerance: int,
) -> None:
    if not signature_header:
        raise InvalidSignature("Missing Stripe-Signature header")
    parts = dict(
        item.split("=", 1) for item in signature_header.split(",") if "=" in item
    )
    timestamp = parts.get("t")
    provided = parts.get("v1")
    if timestamp is None or provided is None:
        raise InvalidSignature("Malformed Stripe-Signature header")
    try:
        if abs(int(time.time()) - int(timestamp)) > tolerance:
            raise InvalidSignature("Stripe webhook timestamp outside tolerance")
    except ValueError as exc:
        raise InvalidSignature("Invalid Stripe timestamp") from exc
    expected = _hex_hmac(secret, f"{timestamp}.".encode() + body)
    if not hmac.compare_digest(provided, expected):
        raise InvalidSignature("Stripe signature mismatch")


def stripe_signature_header(secret: str, body: bytes, timestamp: int) -> str:
    """Build a valid Stripe-Signature header (used by tests and outbound Stripe-style callers)."""

    signature = _hex_hmac(secret, f"{timestamp}.".encode() + body)
    return f"t={timestamp},v1={signature}"


def verify_inbound(
    *,
    provider: str,
    body: bytes,
    headers: Mapping[str, str],
) -> None:
    settings = get_settings()
    secret = _secrets().get(provider)
    if secret is None:
        raise InvalidSignature(f"No signing secret configured for provider '{provider}'")

    if provider == "stripe":
        _verify_stripe(
            secret,
            body,
            headers.get("Stripe-Signature"),
            settings.webhook_tolerance_seconds,
        )
        return
    if provider == "github":
        _verify_generic(secret, body, headers.get("X-Hub-Signature-256"))
        return
    _verify_generic(secret, body, headers.get(settings.webhook_signature_header))


def get_webhook_secret(provider: str) -> str:
    secrets = _secrets()
    return secrets.get(provider) or secrets.get("generic") or "dev-webhook-secret"


def build_delivery_headers(secret: str, body: bytes, event_type: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Webhook-Signature": sign_payload(secret, body),
        "X-Webhook-Event": event_type,
        "X-Webhook-Delivery": str(uuid.uuid4()),
    }
