from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.core.errors import DomainError
from app.core.logging import setup_logging
from app.core.middleware import (
    AccessLogMiddleware,
    RateLimitMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    TimingMiddleware,
)
from app.db.bootstrap import ensure_schema_initialized
from app.db.clients import DataClients, close_data_clients, init_data_clients
from app.db.session import engine
from app.websockets.broker import EventBroker
from app.websockets.realtime import connection_manager
from app.workers.runtime import build_task_queue
from app.workers.scheduler import PeriodicScheduler

try:
    from slowapi import Limiter
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi.util import get_remote_address
except ModuleNotFoundError:  # pragma: no cover - fallback when optional deps are missing
    Limiter = None
    RateLimitExceeded = Exception  # type: ignore[misc,assignment]
    SlowAPIMiddleware = None
    get_remote_address = None

settings = get_settings()
setup_logging(settings.app_debug)
error_logger = logging.getLogger("taskflow.errors")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    app.state.http_client = httpx.AsyncClient(timeout=settings.request_timeout_seconds)
    await ensure_schema_initialized()
    app.state.data_clients = await init_data_clients(app.state.http_client)
    app.state.search_gateway = app.state.data_clients.search_gateway

    # Layer 4: real-time broker, task queue, periodic scheduler.
    redis_client = app.state.data_clients.redis_client
    broker = None
    if redis_client is not None:
        broker = EventBroker(
            redis=redis_client,
            manager=connection_manager,
            channel_prefix=settings.realtime_channel_prefix,
        )
        await broker.start()
    app.state.event_broker = broker
    app.state.task_queue = await build_task_queue(redis=redis_client, broker=broker)

    scheduler = PeriodicScheduler()
    if settings.scheduler_enabled and redis_client is not None:
        queue = app.state.task_queue
        scheduler.add_interval_job(
            lambda: queue.enqueue("relay_outbox"),
            interval_seconds=settings.outbox_relay_interval_seconds,
            job_id="relay_outbox",
        )
        await scheduler.start()
    app.state.scheduler = scheduler
    app.state.started = True

    yield

    await scheduler.stop()
    if broker is not None:
        await broker.stop()
    task_queue = getattr(app.state, "task_queue", None)
    if task_queue is not None:
        await task_queue.close()
    data_clients = getattr(app.state, "data_clients", DataClients())
    await close_data_clients(data_clients)
    await app.state.http_client.aclose()
    await engine.dispose()


def create_admin_app() -> FastAPI:
    admin_app = FastAPI(
        title="TaskFlow Admin",
        version="1.0.0",
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    @admin_app.get("/stats", tags=["admin"])
    async def stats() -> dict[str, Any]:
        return {
            "active": True,
            "message": "Separate sub-application mounted at /admin",
        }

    return admin_app


def custom_openapi(app: FastAPI) -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        summary="Task management platform",
        description="TaskFlow API with modular architecture and production-grade patterns.",
        routes=app.routes,
    )
    schema["info"]["x-logo"] = {"url": "https://example.com/logo.png"}
    components = schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }
    security_schemes["ApiKeyAuth"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }
    app.openapi_schema = schema
    return schema


def _build_slowapi_limit(window_seconds: int, requests: int) -> str:
    return f"{requests}/{window_seconds}seconds"


def build_scalar_html(openapi_url: str, title: str) -> str:
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title} - Scalar</title>
  </head>
  <body>
    <div id="app"></div>
    <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
    <script>
      Scalar.createApiReference('#app', {{
        url: '{openapi_url}',
        theme: 'moon'
      }})
    </script>
  </body>
</html>
"""


def build_stoplight_html(openapi_url: str, title: str) -> str:
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title} - Stoplight Elements</title>
    <script src="https://unpkg.com/@stoplight/elements/web-components.min.js"></script>
    <link rel="stylesheet" href="https://unpkg.com/@stoplight/elements/styles.min.css" />
    <style>
      body {{
        margin: 0;
      }}
    </style>
  </head>
  <body>
    <elements-api
      apiDescriptionUrl="{openapi_url}"
      router="hash"
      layout="sidebar"
    />
  </body>
</html>
"""


def create_app() -> FastAPI:
    docs_url = "/docs" if settings.docs_enabled else None
    redoc_url = "/redoc" if settings.docs_enabled else None
    openapi_url = "/openapi.json" if settings.docs_enabled else None

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="TaskFlow backend for task, team, and integration workflows.",
        summary="Task management platform",
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        openapi_tags=[
            {"name": "auth", "description": "Session and token lifecycle"},
            {"name": "users", "description": "Authentication and user profiles"},
            {"name": "tasks", "description": "Task operations"},
            {"name": "integrations", "description": "External systems import/sync"},
            {"name": "teams", "description": "Team operations"},
            {"name": "jobs", "description": "Background jobs and transactional outbox"},
            {"name": "realtime", "description": "WebSocket real-time channels"},
            {"name": "system", "description": "Infrastructure endpoints"},
            {"name": "admin", "description": "Admin sub-application"},
        ],
        swagger_ui_parameters={
            "defaultModelsExpandDepth": -1,
            "docExpansion": "none",
            "displayRequestDuration": True,
        },
        default_response_class=JSONResponse,
    )

    @app.exception_handler(DomainError)
    async def domain_exception_handler(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {"code": exc.code, "message": exc.message},
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {"code": "validation_error", "details": exc.errors()},
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {"code": "http_error", "message": exc.detail},
                "request_id": getattr(request.state, "request_id", None),
            },
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        error_logger.error(
            "unhandled_exception",
            exc_info=exc,
            extra={
                "request_id": getattr(request.state, "request_id", None),
                "path": request.url.path,
                "method": request.method,
            },
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {"code": "internal_error", "message": "Unexpected server error"},
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    has_slowapi = (
        Limiter is not None
        and SlowAPIMiddleware is not None
        and get_remote_address is not None
    )
    if has_slowapi:
        limiter = Limiter(
            key_func=get_remote_address,
            default_limits=[
                _build_slowapi_limit(
                    window_seconds=settings.rate_limit_window_seconds,
                    requests=settings.rate_limit_requests,
                )
            ],
            headers_enabled=True,
            storage_uri="memory://",
            enabled=settings.rate_limit_enabled,
        )
        app.state.limiter = limiter

        @app.exception_handler(RateLimitExceeded)
        async def rate_limit_exceeded_handler(
            request: Request,
            exc: Exception,
        ) -> JSONResponse:
            retry_after = None
            headers = getattr(exc, "headers", None)
            if isinstance(headers, dict):
                retry_after = headers.get("Retry-After")
            response_headers = {"Retry-After": str(retry_after)} if retry_after else None
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": "Too many requests. Please retry later.",
                    },
                    "request_id": getattr(request.state, "request_id", None),
                },
                headers=response_headers,
            )
    elif settings.rate_limit_enabled:
        error_logger.warning("slowapi_not_installed_using_fallback_rate_limit")

    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)
    app.mount("/admin", create_admin_app())

    if settings.docs_enabled and openapi_url:
        @app.get("/scalar", include_in_schema=False)
        async def scalar_docs() -> HTMLResponse:
            return HTMLResponse(build_scalar_html(openapi_url=openapi_url, title=settings.app_name))

        @app.get("/stoplight", include_in_schema=False)
        async def stoplight_docs() -> HTMLResponse:
            return HTMLResponse(
                build_stoplight_html(openapi_url=openapi_url, title=settings.app_name),
            )

    # Middleware order matters: last added is outermost.
    app.add_middleware(GZipMiddleware, minimum_size=settings.gzip_minimum_size)
    app.add_middleware(TimingMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(AccessLogMiddleware)
    if settings.secure_headers_enabled:
        app.add_middleware(
            SecurityHeadersMiddleware,
            hsts_enabled=settings.hsts_enabled and settings.app_env != "local",
        )
    if has_slowapi:
        app.add_middleware(SlowAPIMiddleware)
    else:
        app.add_middleware(
            RateLimitMiddleware,
            enabled=settings.rate_limit_enabled,
            limit=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
        )
    if settings.app_env != "local":
        app.add_middleware(HTTPSRedirectMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.openapi = lambda: custom_openapi(app)

    return app


app = create_app()
