from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Run a test through the real FastAPI lifespan and middleware stack."""

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
async def async_client() -> AsyncIterator[httpx.AsyncClient]:
    """Exercise FastAPI through httpx without bypassing the application lifespan."""

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as test_client:
            yield test_client


@pytest.fixture
def token_factory(client: TestClient) -> Callable[[str], str]:
    def issue_token(scope: str) -> str:
        response = client.post(
            "/api/v1/users/token",
            data={
                "username": "admin@taskflow.dev",
                "password": "admin12345",
                "scope": scope,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body.get("access_token"), str)
        return body["access_token"]

    return issue_token


@pytest.fixture
def auth_headers(token_factory: Callable[[str], str]) -> Callable[[str], dict[str, str]]:
    def headers(scope: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token_factory(scope)}"}

    return headers


@pytest.fixture
def api_request_headers(
    auth_headers: Callable[[str], dict[str, str]],
) -> Callable[[str], dict[str, str]]:
    def headers(scope: str) -> dict[str, str]:
        return {**auth_headers(scope), "X-API-Key": "local-dev-key"}

    return headers


@pytest.fixture
def json_headers() -> dict[str, str]:
    return {"Content-Type": "application/json"}


@pytest.fixture
def app_state(client: TestClient) -> Any:
    return client.app.state
