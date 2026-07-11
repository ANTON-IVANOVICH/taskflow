import time

import pytest
from freezegun import freeze_time
from hypothesis import given
from hypothesis import strategies as st

from app.core.errors import InvalidSignature
from app.integrations.llm import parse_sse_text_delta
from app.integrations.webhooks import (
    sign_payload,
    stripe_signature_header,
    verify_inbound,
)
from app.storage.presign import sign_upload_token, verify_upload_token

pytestmark = pytest.mark.unit


def test_upload_token_round_trip_and_tamper_detection() -> None:
    token = sign_upload_token(
        secret="secret",
        key="uploads/1/report.txt",
        content_type="text/plain",
        max_size=100,
        expires_at=int(time.time()) + 60,
    )

    claims = verify_upload_token(secret="secret", token=token)
    assert claims["key"] == "uploads/1/report.txt"

    payload, signature = token.split(".")
    tampered = f"{payload[:-1]}{('A' if payload[-1] != 'A' else 'B')}.{signature}"
    with pytest.raises(InvalidSignature):
        verify_upload_token(secret="secret", token=tampered)


def test_upload_token_rejects_expired_and_malformed_values() -> None:
    expired = sign_upload_token(
        secret="secret",
        key="uploads/1/old.txt",
        content_type="text/plain",
        max_size=100,
        expires_at=int(time.time()) - 1,
    )
    with pytest.raises(InvalidSignature, match="expired"):
        verify_upload_token(secret="secret", token=expired)
    with pytest.raises(InvalidSignature, match="Malformed"):
        verify_upload_token(secret="secret", token="not-a-token")


@given(st.text(min_size=1, max_size=80))
def test_upload_token_round_trip_for_generated_keys(key: str) -> None:
    token = sign_upload_token(
        secret="secret",
        key=f"uploads/1/{key}",
        content_type="text/plain",
        max_size=100,
        expires_at=int(time.time()) + 60,
    )

    assert verify_upload_token(secret="secret", token=token)["key"] == f"uploads/1/{key}"


@freeze_time("2026-07-11 12:00:00")
def test_upload_token_expiry_is_deterministic() -> None:
    token = sign_upload_token(
        secret="secret",
        key="uploads/1/frozen.txt",
        content_type="text/plain",
        max_size=100,
        expires_at= int(time.time()) + 60,
    )

    with freeze_time("2026-07-11 12:00:59"):
        assert verify_upload_token(secret="secret", token=token)["key"] == "uploads/1/frozen.txt"
    with freeze_time("2026-07-11 12:01:01"), pytest.raises(InvalidSignature, match="expired"):
        verify_upload_token(secret="secret", token=token)


def test_webhook_signatures_verify_raw_body_and_timestamp() -> None:
    body = b'{"id":"evt_1"}'
    generic_signature = sign_payload("dev-webhook-secret", body)
    verify_inbound(
        provider="generic",
        body=body,
        headers={"X-Webhook-Signature": generic_signature},
    )

    stripe_signature = stripe_signature_header("whsec_dev", body, int(time.time()))
    verify_inbound(provider="stripe", body=body, headers={"Stripe-Signature": stripe_signature})


def test_llm_parser_only_returns_text_delta() -> None:
    assert (
        parse_sse_text_delta(
            '{"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}'
        )
        == "Hi"
    )
    assert parse_sse_text_delta('{"type":"message_stop"}') is None
    assert parse_sse_text_delta("not-json") is None
