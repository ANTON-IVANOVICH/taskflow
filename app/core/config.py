from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "TaskFlow API"
    app_env: str = "local"
    app_debug: bool = True
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite+aiosqlite:///./taskflow.db"
    db_echo: bool = False
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_recycle_seconds: int = 3600
    db_pool_pre_ping: bool = True
    db_seed_enabled: bool = True
    postgres_dsn: str | None = None
    redis_url: str | None = None
    mongo_url: str | None = None
    mongo_db_name: str = "taskflow"
    mongo_events_collection: str = "task_events"
    meilisearch_url: str | None = None
    meilisearch_api_key: str | None = None
    meilisearch_index: str = "tasks"
    jwt_secret_key: str = "dev-insecure-jwt-secret-change-me"
    jwt_issuer: str = "taskflow-api"
    jwt_audience: str = "taskflow-clients"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 1209600

    # NoDecode: keep raw env strings so parse_csv_list (below) can split CSV values.
    # Without it pydantic-settings JSON-decodes list fields from env and rejects "a,b".
    allowed_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    allowed_hosts: Annotated[list[str], NoDecode] = ["localhost", "127.0.0.1", "testserver"]
    gzip_minimum_size: int = 1000
    docs_enabled: bool = True
    request_timeout_seconds: float = 10.0
    csrf_enabled: bool = True
    refresh_cookie_name: str = "refresh_token"
    csrf_cookie_name: str = "csrf_token"
    csrf_header_name: str = "X-CSRF-Token"
    machine_api_keys: str = (
        "local-dev-key=teams:read,tasks:read,tasks:write,integrations:write"
    )
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60
    secure_headers_enabled: bool = True
    hsts_enabled: bool = True
    oauth_google_client_id: str | None = None
    oauth_google_client_secret: str | None = None
    oauth_github_client_id: str | None = None
    oauth_github_client_secret: str | None = None
    oauth_google_authorize_url: str = "https://accounts.google.com/o/oauth2/v2/auth"
    oauth_google_token_url: str = "https://oauth2.googleapis.com/token"
    oauth_google_userinfo_url: str = "https://openidconnect.googleapis.com/v1/userinfo"
    oauth_github_authorize_url: str = "https://github.com/login/oauth/authorize"
    oauth_github_token_url: str = "https://github.com/login/oauth/access_token"
    oauth_github_userinfo_url: str = "https://api.github.com/user"
    oauth_github_user_emails_url: str = "https://api.github.com/user/emails"
    oauth_state_ttl_seconds: int = 600

    # Layer 4 — async, background tasks, real-time
    worker_queue_name: str = "taskflow:jobs"
    worker_eager: bool | None = None
    worker_job_ttl_seconds: int = 3600
    worker_max_jobs: int = 20
    worker_job_timeout_seconds: int = 300
    outbox_relay_batch_size: int = 100
    scheduler_enabled: bool = True
    outbox_relay_interval_seconds: int = 30
    ws_heartbeat_seconds: int = 30
    ws_send_timeout_seconds: float = 5.0
    realtime_channel_prefix: str = "taskflow:rt"

    # Layer 5 — external integrations (resilient HTTP)
    http_connect_timeout: float = 5.0
    http_read_timeout: float = 30.0
    http_write_timeout: float = 10.0
    http_pool_timeout: float = 5.0
    http_max_connections: int = 100
    http_max_keepalive: int = 20
    http_retry_attempts: int = 3
    http_retry_base_delay: float = 0.2
    http_retry_max_delay: float = 10.0
    http_retry_max_after: float = 30.0
    circuit_breaker_threshold: int = 5
    circuit_breaker_reset_seconds: float = 30.0

    # Layer 5 — file storage
    storage_backend: str = "local"
    storage_local_dir: str = "./var/storage"
    storage_url_secret: str = "dev-insecure-storage-secret-change-me"
    storage_presign_ttl_seconds: int = 300
    storage_max_upload_bytes: int = 50 * 1024 * 1024
    storage_allowed_types: str = (
        "text/plain,text/csv,application/pdf,application/json,image/png,image/jpeg"
    )
    s3_bucket: str | None = None
    s3_region: str = "us-east-1"
    s3_endpoint_url: str | None = None

    # Layer 5 — webhooks
    webhook_signing_secrets: str = "stripe=whsec_dev;github=ghsec_dev;generic=dev-webhook-secret"
    webhook_signature_header: str = "X-Webhook-Signature"
    webhook_id_header: str = "X-Webhook-Id"
    webhook_delivery_timeout: float = 10.0
    webhook_tolerance_seconds: int = 300

    # Layer 5 — email
    email_provider: str = "generic"
    email_provider_base_url: str | None = None
    email_api_key: str | None = None
    email_from: str = "TaskFlow <no-reply@taskflow.dev>"
    email_timeout_seconds: float = 15.0

    # Layer 5 — Stripe payments
    stripe_api_key: str | None = None
    stripe_base_url: str = "https://api.stripe.com"
    stripe_timeout_seconds: float = 30.0

    # Layer 5 — LLM
    anthropic_api_key: str | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_model: str = "claude-opus-4-8"
    anthropic_version: str = "2023-06-01"
    llm_max_tokens: int = 1024
    llm_max_concurrency: int = 10
    llm_timeout_seconds: float = 60.0

    @field_validator("allowed_origins", "allowed_hosts", mode="before")
    @classmethod
    def parse_csv_list(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator(
        "worker_eager",
        "postgres_dsn",
        "redis_url",
        "mongo_url",
        "meilisearch_url",
        "meilisearch_api_key",
        "oauth_google_client_id",
        "oauth_google_client_secret",
        "oauth_github_client_id",
        "oauth_github_client_secret",
        "s3_bucket",
        "s3_endpoint_url",
        "email_provider_base_url",
        "email_api_key",
        "stripe_api_key",
        "anthropic_api_key",
        mode="before",
    )
    @classmethod
    def empty_str_to_none(cls, value: object) -> object:
        # An empty value in .env (e.g. `REDIS_URL=`, `OAUTH_GOOGLE_CLIENT_ID=`) means "unset".
        # Without this it stays "" — truthy enough to look configured and break `is None` checks.
        if isinstance(value, str) and value.strip() == "":
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
