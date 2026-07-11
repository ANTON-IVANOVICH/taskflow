from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.factories import TaskCreateFactory

pytestmark = pytest.mark.e2e


def test_registered_user_can_create_update_and_read_task(client: TestClient) -> None:
    email = f"e2e-{uuid4().hex}@taskflow.dev"
    password = "e2e-password-123"

    registered = client.post(
        "/api/v1/users/register",
        json={"email": email, "name": "E2E User", "password": password},
    )
    assert registered.status_code == 201

    token_response = client.post(
        "/api/v1/users/token",
        data={
            "username": email,
            "password": password,
            "scope": "tasks:read tasks:write",
        },
    )
    assert token_response.status_code == 200
    headers = {"Authorization": f"Bearer {token_response.json()['access_token']}"}

    payload = TaskCreateFactory.build().model_dump(mode="json")
    created = client.post("/api/v1/tasks", params={"team_id": 1}, headers=headers, json=payload)
    assert created.status_code == 201
    task_id = created.json()["id"]
    assert created.json()["title"] == payload["title"]

    updated = client.put(
        f"/api/v1/tasks/{task_id}",
        headers=headers,
        json={"status": "done"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "done"

    fetched = client.get(f"/api/v1/tasks/{task_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == task_id
    assert fetched.json()["status"] == "done"
