from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_invalid_webhook_signature_returns_domain_error(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/webhooks/generic",
        headers={"X-Webhook-Signature": "sha256=invalid"},
        json={"id": "negative-webhook"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_signature"


async def test_async_client_preserves_webhook_error_contract(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.post(
        "/api/v1/webhooks/generic",
        headers={"X-Webhook-Signature": "sha256=invalid"},
        json={"id": "async-negative-webhook"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_signature"


def test_presign_rejects_unsupported_content_type(
    client: TestClient,
    token_factory: Callable[[str], str],
) -> None:
    response = client.post(
        "/api/v1/files/presigned-upload",
        headers={"Authorization": f"Bearer {token_factory('tasks:write')}"},
        json={"filename": "script.exe", "content_type": "application/x-msdownload", "size": 10},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_presign_rejects_files_over_configured_limit(
    client: TestClient,
    token_factory: Callable[[str], str],
) -> None:
    response = client.post(
        "/api/v1/files/presigned-upload",
        headers={"Authorization": f"Bearer {token_factory('tasks:write')}"},
        json={"filename": "huge.txt", "content_type": "text/plain", "size": 50 * 1024 * 1024 + 1},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_checkout_requires_stripe_configuration(
    client: TestClient,
    token_factory: Callable[[str], str],
) -> None:
    response = client.post(
        "/api/v1/payments/checkout",
        headers={"Authorization": f"Bearer {token_factory('integrations:write')}"},
        json={
            "amount": 1000,
            "currency": "usd",
            "description": "Configuration test",
            "success_url": "https://taskflow.test/success",
            "cancel_url": "https://taskflow.test/cancel",
            "idempotency_key": "missing-stripe-key",
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "integration_not_configured"
