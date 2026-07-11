import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.concurrency import bounded_gather, gather_mapping
from app.main import app

client = TestClient(app)


def issue_token(scope: str) -> str:
    response = client.post(
        "/api/v1/users/token",
        data={"username": "admin@taskflow.dev", "password": "admin12345", "scope": scope},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def auth(scope: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token(scope)}"}


# --- Background jobs / queue (eager fallback) -----------------------------------------------


def test_enqueue_report_job_runs_eagerly() -> None:
    response = client.post(
        "/api/v1/jobs/reports",
        headers=auth("tasks:write"),
        json={"team_id": 1, "report_format": "summary"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "complete"
    job_id = body["job_id"]

    status_response = client.get(f"/api/v1/jobs/{job_id}", headers=auth("tasks:read"))
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["status"] == "complete"
    result = status_body["result"]
    assert result["team_id"] == 1
    assert "by_status" in result
    assert "fingerprint" in result
    assert len(status_body["progress"]) == 3


def test_job_status_not_found() -> None:
    response = client.get("/api/v1/jobs/does-not-exist", headers=auth("tasks:read"))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"


def test_job_progress_streamed_as_sse() -> None:
    enqueue = client.post(
        "/api/v1/jobs/reports",
        headers=auth("tasks:write"),
        json={"team_id": 1},
    )
    job_id = enqueue.json()["job_id"]

    response = client.get(
        f"/api/v1/jobs/{job_id}/events",
        headers={**auth("tasks:read"), "Accept": "text/event-stream"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: progress" in response.text
    assert "report ready" in response.text
    assert "event: complete" in response.text


def test_enqueue_report_requires_write_scope() -> None:
    response = client.post(
        "/api/v1/jobs/reports",
        headers=auth("tasks:read"),
        json={"team_id": 1},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


# --- Transactional outbox -------------------------------------------------------------------


def test_outbox_relay_publishes_then_idempotent() -> None:
    create = client.post(
        "/api/v1/tasks",
        params={"team_id": 1},
        headers=auth("tasks:write"),
        json={"title": "Outbox subject", "priority": 2, "tags": ["outbox"]},
    )
    assert create.status_code == 201

    first = client.post("/api/v1/jobs/outbox/relay", headers=auth("admin"))
    assert first.status_code == 200
    assert first.json()["published"] >= 1

    second = client.post("/api/v1/jobs/outbox/relay", headers=auth("admin"))
    assert second.status_code == 200
    assert second.json()["published"] == 0


def test_outbox_relay_requires_admin() -> None:
    response = client.post("/api/v1/jobs/outbox/relay", headers=auth("tasks:write"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


# --- Parallel aggregation / worker metrics --------------------------------------------------


def test_dashboard_parallel_aggregation() -> None:
    response = client.get(
        "/api/v1/tasks/dashboard",
        params={"team_id": 1},
        headers=auth("tasks:read"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["team_id"] == 1
    assert isinstance(body["status_counts"], dict)
    assert isinstance(body["recent"], list)
    assert body["pulse"]["window"] == "24h"


def test_worker_metrics_report_counters() -> None:
    client.post("/api/v1/jobs/reports", headers=auth("tasks:write"), json={"team_id": 1})

    response = client.get("/api/v1/system/worker-metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["jobs_processed"] >= 1
    assert body["jobs_failed"] >= 0
    assert body["outbox_pending"] >= 0
    assert body["ws_active_connections"] >= 0


# --- WebSockets -----------------------------------------------------------------------------
#
# TestClient runs every WebSocket in its own event loop, so a test that mixes an HTTP call into
# an open socket, or holds two sockets at once, would await sends across loops and deadlock. We
# therefore drive single-connection behaviour through TestClient and the broadcast/manager logic
# (used by the REST-update -> WS path) through single-loop async unit tests with fake sockets.


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


class BrokenWebSocket:
    async def send_json(self, message: dict) -> None:
        raise RuntimeError("connection closed")


def test_ws_rejects_missing_token() -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/ws/tasks/1") as ws:
            ws.receive_json()


def test_ws_ping_pong() -> None:
    token = issue_token("tasks:read")
    with client.websocket_connect(f"/api/v1/ws/tasks/1?token={token}") as ws:
        assert ws.receive_json() == {"type": "connected", "task_id": 1}
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


@pytest.mark.asyncio
async def test_connection_manager_broadcast_excludes_sender() -> None:
    from app.websockets.manager import ConnectionManager

    manager = ConnectionManager()
    sender, receiver = FakeWebSocket(), FakeWebSocket()
    await manager.connect("room:1", sender, user_id=1)  # type: ignore[arg-type]
    await manager.connect("room:1", receiver, user_id=2)  # type: ignore[arg-type]

    delivered = await manager.broadcast("room:1", {"text": "hi"}, exclude_user=1)
    assert delivered == 1
    assert sender.sent == []
    assert receiver.sent == [{"text": "hi"}]


@pytest.mark.asyncio
async def test_connection_manager_drops_dead_connections() -> None:
    from app.websockets.manager import ConnectionManager

    manager = ConnectionManager()
    good, dead = FakeWebSocket(), BrokenWebSocket()
    await manager.connect("room:2", good, user_id=1)  # type: ignore[arg-type]
    await manager.connect("room:2", dead, user_id=2)  # type: ignore[arg-type]

    delivered = await manager.broadcast("room:2", {"text": "hi"})
    assert delivered == 1
    assert manager.active_connections == 1


@pytest.mark.asyncio
async def test_broadcast_task_event_falls_back_to_local_manager() -> None:
    from types import SimpleNamespace

    from app.websockets.realtime import broadcast_task_event, connection_manager, task_room

    socket = FakeWebSocket()
    room = task_room(99)
    await connection_manager.connect(room, socket, user_id=1)  # type: ignore[arg-type]
    try:
        fake_app = SimpleNamespace(state=SimpleNamespace())
        await broadcast_task_event(fake_app, room, {"type": "task_event", "task_id": 99})
        assert socket.sent[-1]["task_id"] == 99
    finally:
        await connection_manager.disconnect(room, socket, user_id=1)  # type: ignore[arg-type]


# --- Concurrency helpers --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bounded_gather_preserves_order_and_caps_concurrency() -> None:
    active = 0
    peak = 0

    def factory(value: int):
        async def run() -> int:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.005)
            active -= 1
            return value

        return run

    results = await bounded_gather([factory(i) for i in range(10)], limit=3)
    assert results == list(range(10))
    assert peak <= 3


@pytest.mark.asyncio
async def test_gather_mapping_keys_align_with_results() -> None:
    async def value(v: int) -> int:
        await asyncio.sleep(0)
        return v

    result = await gather_mapping({"a": value(1), "b": value(2)})
    assert result == {"a": 1, "b": 2}


# --- OpenAPI ---------------------------------------------------------------------------------


def test_openapi_exposes_async_runtime_paths() -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/jobs/reports" in paths
    assert "/api/v1/jobs/{job_id}" in paths
    assert "/api/v1/jobs/{job_id}/events" in paths
    assert "/api/v1/jobs/outbox/relay" in paths
    assert "/api/v1/tasks/dashboard" in paths
    assert "/api/v1/system/worker-metrics" in paths
