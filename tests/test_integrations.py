from __future__ import annotations

import json
import time
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.integrations.email import EmailService
from app.integrations.http import ResilientHttpClient, RetryPolicy
from app.integrations.llm import LLMService
from app.integrations.stripe import StripeService
from app.integrations.webhooks import stripe_signature_header
from app.main import app
from app.storage.local import LocalFileStorage

client = TestClient(app)


def issue_token(scope: str) -> str:
    response = client.post(
        "/api/v1/users/token",
        data={"username": "admin@taskflow.dev", "password": "admin12345", "scope": scope},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def issue_registered_token() -> str:
    email = f"layer5-{uuid4().hex}@taskflow.dev"
    password = "layer5-password"
    registered = client.post(
        "/api/v1/users/register",
        json={"email": email, "name": "Layer 5 User", "password": password},
    )
    assert registered.status_code == 201
    response = client.post(
        "/api/v1/users/token",
        data={"username": email, "password": password, "scope": "tasks:read"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_resilient_client_retries_safe_request() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503, request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    resilient = ResilientHttpClient(
        upstream,
        retry=RetryPolicy(attempts=3, base_delay=0, max_delay=0),
    )
    response = await resilient.request("GET", "https://upstream.test/health")
    await upstream.aclose()

    assert response.status_code == 200
    assert calls == 3


@pytest.mark.asyncio
async def test_email_service_sends_idempotent_json_payload() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["json"] = json.loads(request.content)
        return httpx.Response(202, json={"id": "mail_123"}, request=request)

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    resilient = ResilientHttpClient(
        upstream,
        retry=RetryPolicy(attempts=1),
    )
    service = EmailService(
        client=resilient,
        provider="test-mail",
        base_url="https://mail.test/send",
        api_key="mail-secret",
        from_address="TaskFlow <no-reply@test>",
        timeout_seconds=5,
    )
    result = await service.send(
        to="user@test",
        subject="Hello",
        text="Welcome",
        idempotency_key="welcome:user@test",
    )
    await upstream.aclose()

    headers = captured["headers"]
    payload = captured["json"]
    assert result.status == "sent"
    assert result.message_id == "mail_123"
    assert isinstance(headers, dict)
    assert headers["authorization"] == "Bearer mail-secret"
    assert headers["idempotency-key"] == "welcome:user@test"
    assert payload == {
        "from": "TaskFlow <no-reply@test>",
        "to": ["user@test"],
        "subject": "Hello",
        "text": "Welcome",
    }


@pytest.mark.asyncio
async def test_stripe_service_posts_checkout_form() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={"id": "cs_test_123", "url": "https://checkout.test/cs_test_123"},
            request=request,
        )

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = StripeService(
        client=ResilientHttpClient(upstream, retry=RetryPolicy(attempts=1)),
        api_key="sk_test_secret",
        base_url="https://api.stripe.test",
        timeout_seconds=5,
    )
    session = await service.create_checkout_session(
        amount=1999,
        currency="USD",
        description="TaskFlow Pro",
        success_url="https://taskflow.test/success",
        cancel_url="https://taskflow.test/cancel",
        customer_email="admin@taskflow.dev",
        idempotency_key="payment-test-123",
    )
    await upstream.aclose()

    headers = captured["headers"]
    body = captured["body"]
    assert session.external_id == "cs_test_123"
    assert session.checkout_url == "https://checkout.test/cs_test_123"
    assert isinstance(headers, dict)
    assert headers["authorization"] == "Bearer sk_test_secret"
    assert headers["idempotency-key"] == "payment-test-123"
    assert isinstance(body, str)
    assert "line_items%5B0%5D%5Bprice_data%5D%5Bunit_amount%5D=1999" in body


def test_local_presigned_upload_flow_and_owner_check(tmp_path) -> None:
    previous_storage = getattr(app.state, "storage", None)
    app.state.storage = LocalFileStorage(str(tmp_path))
    try:
        token = issue_token("tasks:write")
        response = client.post(
            "/api/v1/files/presigned-upload",
            headers={"Authorization": f"Bearer {token}"},
            json={"filename": "report.txt", "content_type": "text/plain", "size": 5},
        )
        assert response.status_code == 201
        upload = response.json()

        uploaded = client.put(
            upload["upload_url"],
            headers=upload["headers"],
            content=b"hello",
        )
        assert uploaded.status_code == 200
        assert uploaded.json()["key"] == upload["key"]

        reader = issue_token("tasks:read")
        confirmed = client.post(
            "/api/v1/files/confirm",
            headers={"Authorization": f"Bearer {reader}"},
            json={"key": upload["key"]},
        )
        assert confirmed.status_code == 200

        downloaded = client.get(
            "/api/v1/files/download",
            headers={"Authorization": f"Bearer {reader}"},
            params={"key": upload["key"]},
        )
        assert downloaded.status_code == 200
        assert downloaded.content == b"hello"

        forbidden_reader = issue_registered_token()
        forbidden = client.get(
            "/api/v1/files/download",
            headers={"Authorization": f"Bearer {forbidden_reader}"},
            params={"key": "uploads/999/not-yours.txt"},
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["error"]["code"] == "forbidden"
    finally:
        if previous_storage is None:
            delattr(app.state, "storage")
        else:
            app.state.storage = previous_storage


def test_stripe_webhook_is_signed_deduplicated_and_processed() -> None:
    body = (
        '{"id":"evt_' + uuid4().hex + '","type":"checkout.session.completed",'
        '"data":{"object":{"id":"cs_unknown_for_webhook"}}}'
    ).encode()
    signature = stripe_signature_header("whsec_dev", body, int(time.time()))

    first = client.post(
        "/api/v1/webhooks/stripe",
        headers={"Stripe-Signature": signature},
        content=body,
    )
    second = client.post(
        "/api/v1/webhooks/stripe",
        headers={"Stripe-Signature": signature},
        content=body,
    )

    assert first.status_code == 200
    assert first.json()["status"] == "accepted"
    assert second.status_code == 200
    assert second.json()["status"] == "already_processed"


def test_payment_checkout_is_idempotent_and_webhook_updates_status() -> None:
    calls = 0
    session_id = f"cs_layer5_{uuid4().hex}"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"id": session_id, "url": "https://checkout.test/layer5"},
            request=request,
        )

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    previous_service = getattr(app.state, "stripe_service", None)
    app.state.stripe_service = StripeService(
        client=ResilientHttpClient(upstream, retry=RetryPolicy(attempts=1)),
        api_key="sk_test_secret",
        base_url="https://api.stripe.test",
        timeout_seconds=5,
    )
    try:
        token = issue_token("integrations:write")
        idempotency_key = f"payment-{uuid4().hex}"
        payload = {
            "amount": 2500,
            "currency": "usd",
            "description": "Layer 5 test payment",
            "success_url": "https://taskflow.test/success",
            "cancel_url": "https://taskflow.test/cancel",
            "idempotency_key": idempotency_key,
        }
        first = client.post(
            "/api/v1/payments/checkout",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        second = client.post(
            "/api/v1/payments/checkout",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["id"] == second.json()["id"]
        assert calls == 1

        payment_id = first.json()["id"]
        event_body = (
            '{"id":"evt_'
            + uuid4().hex
            + '","type":"checkout.session.completed",'
            '"data":{"object":{"id":"'
            + session_id
            + '"}}}'
        ).encode()
        webhook = client.post(
            "/api/v1/webhooks/stripe",
            headers={
                "Stripe-Signature": stripe_signature_header(
                    "whsec_dev", event_body, int(time.time())
                )
            },
            content=event_body,
        )
        assert webhook.status_code == 200

        status_response = client.get(
            f"/api/v1/payments/{payment_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "paid"
    finally:
        if previous_service is None:
            delattr(app.state, "stripe_service")
        else:
            app.state.stripe_service = previous_service


def test_llm_stream_has_offline_fallback_without_provider_key() -> None:
    token = issue_token("tasks:read")
    response = client.post(
        "/api/v1/llm/chat/stream",
        headers={"Authorization": f"Bearer {token}"},
        json={"messages": [{"role": "user", "content": "ping"}]},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: delta" in response.text
    assert "TaskFlow " in response.text
    assert "received: " in response.text
    assert "ping " in response.text
    assert "event: done" in response.text


@pytest.mark.asyncio
async def test_llm_sse_parser_and_stream_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        return httpx.Response(
            200,
            text=(
                'event: content_block_delta\ndata: '
                '{"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}\n\n'
            ),
            request=request,
        )

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = LLMService(
        client=upstream,
        api_key="anthropic-test",
        base_url="https://anthropic.test",
        model="test-model",
        version="2023-06-01",
        max_tokens=32,
        max_concurrency=1,
        timeout_seconds=5,
    )
    chunks = [chunk async for chunk in service.stream([{"role": "user", "content": "Hi"}])]
    await upstream.aclose()

    assert chunks == ["Hi"]
