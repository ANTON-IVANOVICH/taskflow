from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    allowed_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
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

    @field_validator("allowed_origins", "allowed_hosts", mode="before")
    @classmethod
    def parse_csv_list(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
