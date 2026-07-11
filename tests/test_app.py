from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def issue_token(scope: str) -> str:
    return issue_token_for_user(
        email="admin@taskflow.dev",
        password="admin12345",
        scope=scope,
    )


def issue_token_for_user(email: str, password: str, scope: str) -> str:
    response = client.post(
        "/api/v1/users/token",
        data={
            "username": email,
            "password": password,
            "scope": scope,
        },
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def issue_token_pair(scope: str, user_agent: str, device_id: str) -> tuple[str, str, str]:
    response = client.post(
        "/api/v1/users/token",
        headers={"User-Agent": user_agent, "X-Device-Id": device_id},
        data={
            "username": "admin@taskflow.dev",
            "password": "admin12345",
            "scope": scope,
        },
    )
    assert response.status_code == 200
    body = response.json()
    csrf_token = body.get("csrf_token")
    assert isinstance(csrf_token, str)
    return body["access_token"], body["refresh_token"], csrf_token


def test_health() -> None:
    response = client.get("/api/v1/system/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "x-ratelimit-limit" in response.headers
    assert "x-ratelimit-remaining" in response.headers


def test_validation_error_contract() -> None:
    token = issue_token("tasks:write")
    response = client.post(
        "/api/v1/tasks",
        params={"team_id": 1},
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "", "priority": 10, "tags": ["ops"]},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert "details" in body["error"]


def test_list_tasks_with_scope() -> None:
    token = issue_token("tasks:read")
    response = client.get(
        "/api/v1/tasks",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_list_tasks_with_full_text_search() -> None:
    token = issue_token("tasks:read")
    response = client.get(
        "/api/v1/tasks",
        headers={"Authorization": f"Bearer {token}"},
        params={"search": "incident"},
    )

    assert response.status_code == 200
    items = response.json()
    assert len(items) >= 1
    assert any("incident" in item["title"].lower() for item in items)


def test_update_task_requires_write_scope() -> None:
    token = issue_token("tasks:read")
    response = client.put(
        "/api/v1/tasks/1",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "Updated"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_teams_requires_api_key() -> None:
    token = issue_token("teams:read")
    response = client.get(
        "/api/v1/teams",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_teams_with_api_key() -> None:
    token = issue_token("teams:read")
    response = client.get(
        "/api/v1/teams",
        headers={
            "Authorization": f"Bearer {token}",
            "X-API-Key": "local-dev-key",
        },
    )

    assert response.status_code == 200
    assert len(response.json()) >= 1


def test_create_team_requires_admin_role() -> None:
    email = f"analyst-{uuid4().hex}@taskflow.dev"
    register_response = client.post(
        "/api/v1/users/register",
        json={
            "email": email,
            "name": "Analyst RBAC",
            "password": "analyst12345",
        },
    )
    assert register_response.status_code == 201

    token = issue_token_for_user(
        email=email,
        password="analyst12345",
        scope="teams:read",
    )
    response = client.post(
        "/api/v1/teams",
        headers={
            "Authorization": f"Bearer {token}",
            "X-API-Key": "local-dev-key",
        },
        json={"name": "Finance Ops"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_import_tasks_with_wrapped_payload() -> None:
    token = issue_token("tasks:write")
    response = client.post(
        "/api/v1/tasks/import",
        params={"team_id": 1},
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider": "jira",
            "payload": [
                {
                    "external_id": "JIRA-130",
                    "title": "Imported from Jira",
                    "priority": 4,
                    "tags": ["integration", "jira"],
                }
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["provider"] == "jira"
    assert body["imported"] == 1
    assert len(body["tasks"]) == 1
    assert body["tasks"][0]["title"] == "Imported from Jira"


def test_m2m_api_key_can_read_teams_without_bearer() -> None:
    response = client.get(
        "/api/v1/teams",
        headers={"X-API-Key": "local-dev-key"},
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_import_tasks_from_provider_endpoint() -> None:
    token = issue_token("integrations:write")
    response = client.post(
        "/api/v1/integrations/trello/tasks",
        params={"team_id": 1},
        headers={"Authorization": f"Bearer {token}"},
        json={
            "payload": [
                {
                    "external_id": "TR-501",
                    "title": "Imported from Trello",
                    "priority": 3,
                    "tags": ["integration", "trello"],
                }
            ]
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["provider"] == "trello"
    assert body["imported"] == 1
    assert body["tasks"][0]["title"] == "Imported from Trello"


def test_preview_task_description_markdown() -> None:
    token = issue_token("tasks:write")
    response = client.post(
        "/api/v1/tasks/description/preview",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "format": "markdown",
            "content": "# Incident\n- Investigate latency\n- Notify team\nEscalate to **on-call**.",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<h1>Incident</h1>" in response.text
    assert "<li>Investigate latency</li>" in response.text
    assert "<strong>on-call</strong>" in response.text


def test_preview_task_description_html_sanitized() -> None:
    token = issue_token("tasks:write")
    response = client.post(
        "/api/v1/tasks/description/preview",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "format": "html",
            "content": (
                '<h2>Release</h2><script>alert("x")</script>'
                '<p onclick="run()">Deploy <a href="javascript:alert(1)">now</a></p>'
            ),
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<h2>Release</h2>" in response.text
    assert "<script" not in response.text.lower()
    assert "onclick=" not in response.text.lower()
    assert 'href="#"' in response.text


def test_refresh_access_token_from_cookie_and_headers() -> None:
    user_agent = "TaskFlowTest/1.0"
    device_id = "macbook-air-01"
    old_access_token, old_refresh_token, csrf_token = issue_token_pair(
        scope="tasks:read tasks:write",
        user_agent=user_agent,
        device_id=device_id,
    )
    assert old_access_token.count(".") == 2

    response = client.post(
        "/api/v1/auth/refresh",
        headers={
            "User-Agent": user_agent,
            "X-Device-Id": device_id,
            "X-CSRF-Token": csrf_token,
            "Cookie": f"refresh_token={old_refresh_token}; csrf_token={csrf_token}",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"].count(".") == 2
    assert body["refresh_token"].count(".") == 2
    assert body["refresh_token"] != old_refresh_token
    assert "refresh_token=" in response.headers["set-cookie"]


def test_refresh_rejects_mismatched_device() -> None:
    user_agent = "TaskFlowTest/1.0"
    _, refresh_token, csrf_token = issue_token_pair(
        scope="tasks:read",
        user_agent=user_agent,
        device_id="device-a",
    )

    response = client.post(
        "/api/v1/auth/refresh",
        headers={
            "User-Agent": user_agent,
            "X-Device-Id": "device-b",
            "X-CSRF-Token": csrf_token,
            "Cookie": f"refresh_token={refresh_token}; csrf_token={csrf_token}",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_refresh_rejects_missing_csrf_header() -> None:
    user_agent = "TaskFlowTest/1.0"
    _, refresh_token, csrf_token = issue_token_pair(
        scope="tasks:read",
        user_agent=user_agent,
        device_id="device-a",
    )

    response = client.post(
        "/api/v1/auth/refresh",
        headers={
            "User-Agent": user_agent,
            "X-Device-Id": "device-a",
            "Cookie": f"refresh_token={refresh_token}; csrf_token={csrf_token}",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_oauth_provider_login_requires_client_config() -> None:
    response = client.get(
        "/api/v1/auth/oauth/google/login",
        params={"redirect_uri": "http://127.0.0.1:8000/oauth/callback"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_upload_task_attachment() -> None:
    token = issue_token("tasks:write")
    response = client.post(
        "/api/v1/tasks/1/attachments",
        headers={"Authorization": f"Bearer {token}"},
        files={"attachment": ("demo.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["task_id"] == 1
    assert body["filename"] == "demo.txt"
    assert body["content_type"] == "text/plain"
    assert body["size"] == 5


def test_download_task_attachment() -> None:
    writer_token = issue_token("tasks:write")
    upload_response = client.post(
        "/api/v1/tasks/1/attachments",
        headers={"Authorization": f"Bearer {writer_token}"},
        files={"attachment": ("report.txt", b"binary-report", "text/plain")},
    )
    assert upload_response.status_code == 201
    attachment_id = upload_response.json()["id"]

    reader_token = issue_token("tasks:read")
    response = client.get(
        f"/api/v1/tasks/1/attachments/{attachment_id}",
        headers={"Authorization": f"Bearer {reader_token}"},
    )

    assert response.status_code == 200
    assert response.content == b"binary-report"
    assert response.headers["content-type"].startswith("text/plain")
    assert 'attachment; filename="report.txt"' == response.headers["content-disposition"]


def test_export_tasks_csv_with_filters() -> None:
    token = issue_token("tasks:read")
    response = client.get(
        "/api/v1/tasks/export.csv",
        headers={"Authorization": f"Bearer {token}"},
        params={"team_id": 1, "status": "blocked", "assignee": "bob@taskflow.dev"},
    )

    assert response.status_code == 200
    text = response.text
    assert text.startswith("id,title,status,assignee,priority,team_id,created_at,tags")
    assert "blocked,bob@taskflow.dev" in text
    assert "in_progress,alice@taskflow.dev" not in text


def test_stream_task_events() -> None:
    writer_token = issue_token("tasks:write")
    update_response = client.put(
        "/api/v1/tasks/1",
        headers={"Authorization": f"Bearer {writer_token}"},
        json={"priority": 4, "tags": ["events"]},
    )
    assert update_response.status_code == 200

    reader_token = issue_token("tasks:read")
    response = client.get(
        "/api/v1/tasks/1/events/stream",
        headers={
            "Authorization": f"Bearer {reader_token}",
            "Accept": "text/event-stream",
        },
        params={"limit": 5},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: task_updated" in response.text
    assert '"task_id": 1' in response.text


def test_swagger_ui_customization_enabled() -> None:
    assert app.swagger_ui_parameters is not None
    assert app.swagger_ui_parameters["defaultModelsExpandDepth"] == -1


def test_openapi_schema_available() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    body = response.json()
    assert body["openapi"].startswith("3.")
    assert "/api/v1/tasks/import" in body["paths"]
    assert "/api/v1/integrations/{provider}/tasks" in body["paths"]
    assert "/api/v1/tasks/description/preview" in body["paths"]
    assert "/api/v1/auth/refresh" in body["paths"]
    assert "/api/v1/auth/oauth/{provider}/login" in body["paths"]
    assert "/api/v1/auth/oauth/{provider}/callback" in body["paths"]
    assert "/api/v1/tasks/export.csv" in body["paths"]
    assert "/api/v1/tasks/{task_id}/events/stream" in body["paths"]
    assert "/api/v1/tasks/{task_id}/attachments/{attachment_id}" in body["paths"]
    assert "/api/v1/system/download/sample" not in body["paths"]
    assert "/api/v1/system/export.csv" not in body["paths"]
    assert "/api/v1/system/events" not in body["paths"]
    assert "/api/v1/system/request-context" not in body["paths"]
    assert "/api/v1/system/preview" not in body["paths"]
    assert "/api/v1/tasks/embedded" not in body["paths"]
    schemes = body.get("components", {}).get("securitySchemes", {})
    assert "BearerAuth" in schemes
    assert "ApiKeyAuth" in schemes


def test_scalar_docs_page_available() -> None:
    response = client.get("/scalar")

    assert response.status_code == 200
    assert "@scalar/api-reference" in response.text
    assert "/openapi.json" in response.text


def test_stoplight_docs_page_available() -> None:
    response = client.get("/stoplight")

    assert response.status_code == 200
    assert "@stoplight/elements" in response.text
    assert "/openapi.json" in response.text
