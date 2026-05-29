import secrets
import time
from dataclasses import dataclass
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Cookie, Header, Path, Query, Request, Response

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.schemas.users import TokenOut
from app.services import users as user_service

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
OAuthProvider = Literal["google", "github"]


@dataclass(frozen=True)
class OAuthProviderConfig:
    authorize_url: str
    token_url: str
    userinfo_url: str
    client_id: str | None
    client_secret: str | None
    default_scope: str


@dataclass(frozen=True)
class OAuthStateContext:
    provider: OAuthProvider
    redirect_uri: str
    code_verifier: str
    expires_at: float


_OAUTH_STATES: dict[str, OAuthStateContext] = {}


@router.post("/refresh", response_model=TokenOut, summary="Refresh access token")
async def refresh_access_token(
    response: Response,
    user_agent: Annotated[str, Header(alias="User-Agent", min_length=1)],
    device_id: Annotated[str, Header(alias="X-Device-Id", min_length=1, max_length=120)],
    csrf_header: Annotated[
        str | None,
        Header(alias=settings.csrf_header_name, min_length=1),
    ] = None,
    refresh_token: Annotated[
        str | None,
        Cookie(alias=settings.refresh_cookie_name, description="Refresh token in HttpOnly cookie"),
    ] = None,
    csrf_cookie: Annotated[
        str | None,
        Cookie(alias=settings.csrf_cookie_name, description="CSRF cookie token"),
    ] = None,
) -> TokenOut:
    if refresh_token is None:
        raise UnauthorizedError("Missing refresh token cookie")
    if settings.csrf_enabled and (csrf_header is None or csrf_cookie is None):
        raise UnauthorizedError("Missing CSRF token")
    if settings.csrf_enabled and csrf_header != csrf_cookie:
        raise UnauthorizedError("CSRF header does not match cookie")

    token_out = user_service.refresh_access_token(
        refresh_token=refresh_token,
        user_agent=user_agent,
        device_id=device_id,
        csrf_token=csrf_header,
    )
    _set_session_cookies(response=response, token_out=token_out)
    return token_out


@router.get("/oauth/{provider}/login", summary="Build OAuth2 provider authorize URL")
async def oauth_provider_login(
    provider: Annotated[OAuthProvider, Path(description="OAuth provider")],
    redirect_uri: Annotated[str, Query(min_length=1, description="OAuth callback URI")],
    scope: Annotated[str | None, Query(description="Provider scopes override")] = None,
) -> dict[str, str]:
    provider_config = _get_provider_config(provider)
    if provider_config.client_id is None:
        raise UnauthorizedError(f"OAuth provider `{provider}` is not configured")

    state = secrets.token_urlsafe(24)
    code_verifier = secrets.token_urlsafe(64)
    client = _build_oauth_client(
        provider_config=provider_config,
        redirect_uri=redirect_uri,
        scope=scope,
    )
    try:
        authorization_url, auth_state = client.create_authorization_url(
            provider_config.authorize_url,
            state=state,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
    finally:
        await _close_oauth_client(client)

    _OAUTH_STATES[auth_state] = OAuthStateContext(
        provider=provider,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
        expires_at=time.time() + settings.oauth_state_ttl_seconds,
    )
    return {
        "provider": provider,
        "authorization_url": authorization_url,
        "state": auth_state,
    }


@router.get("/oauth/{provider}/callback", summary="Exchange OAuth2 code and issue session")
async def oauth_provider_callback(
    request: Request,
    response: Response,
    provider: Annotated[OAuthProvider, Path(description="OAuth provider")],
    code: Annotated[str, Query(min_length=1, description="Authorization code")],
    state: Annotated[str, Query(min_length=1, description="CSRF state token")],
    user_agent: Annotated[str | None, Header(alias="User-Agent")] = None,
    device_id: Annotated[str | None, Header(alias="X-Device-Id")] = None,
) -> dict[str, Any]:
    state_context = _OAUTH_STATES.pop(state, None)
    if state_context is None or time.time() > state_context.expires_at:
        raise UnauthorizedError("Invalid or expired OAuth state")
    if state_context.provider != provider:
        raise UnauthorizedError("OAuth state provider mismatch")

    provider_config = _get_provider_config(provider)
    if provider_config.client_id is None or provider_config.client_secret is None:
        raise UnauthorizedError(f"OAuth provider `{provider}` is not fully configured")

    callback_url = str(request.url)
    if "code=" not in callback_url:
        callback_url = (
            f"{state_context.redirect_uri}?code={quote(code)}&state={quote(state)}"
        )

    client = _build_oauth_client(
        provider_config=provider_config,
        redirect_uri=state_context.redirect_uri,
        scope=None,
    )
    try:
        token = await client.fetch_token(
            provider_config.token_url,
            authorization_response=callback_url,
            code_verifier=state_context.code_verifier,
        )
        profile = await _fetch_provider_profile(provider=provider, token=token, client=client)
    except Exception as exc:  # noqa: BLE001
        raise UnauthorizedError(f"OAuth callback failed for provider `{provider}`") from exc
    finally:
        await _close_oauth_client(client)

    email = profile.get("email")
    if not isinstance(email, str) or not email:
        raise UnauthorizedError("OAuth provider did not return a user email")
    name_raw = profile.get("name")
    name = name_raw if isinstance(name_raw, str) and name_raw.strip() else email

    token_out = user_service.authenticate_oauth_identity(
        email=email,
        name=name,
        user_agent=user_agent,
        device_id=device_id,
    )
    _set_session_cookies(response=response, token_out=token_out)
    return {
        "provider": provider,
        "status": "authenticated",
        "email": email,
        "token": token_out.model_dump(),
    }


def _set_session_cookies(response: Response, token_out: TokenOut) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token_out.refresh_token,
        httponly=True,
        samesite="lax",
        secure=settings.app_env != "local",
        path="/",
    )
    if settings.csrf_enabled and token_out.csrf_token is not None:
        response.set_cookie(
            key=settings.csrf_cookie_name,
            value=token_out.csrf_token,
            httponly=False,
            samesite="lax",
            secure=settings.app_env != "local",
            path="/",
        )


def _get_provider_config(provider: OAuthProvider) -> OAuthProviderConfig:
    if provider == "google":
        return OAuthProviderConfig(
            authorize_url=settings.oauth_google_authorize_url,
            token_url=settings.oauth_google_token_url,
            userinfo_url=settings.oauth_google_userinfo_url,
            client_id=settings.oauth_google_client_id,
            client_secret=settings.oauth_google_client_secret,
            default_scope="openid email profile",
        )
    return OAuthProviderConfig(
        authorize_url=settings.oauth_github_authorize_url,
        token_url=settings.oauth_github_token_url,
        userinfo_url=settings.oauth_github_userinfo_url,
        client_id=settings.oauth_github_client_id,
        client_secret=settings.oauth_github_client_secret,
        default_scope="read:user user:email",
    )


def _build_oauth_client(
    provider_config: OAuthProviderConfig,
    redirect_uri: str,
    scope: str | None,
) -> Any:
    async_oauth_client = _load_authlib_oauth_client()
    return async_oauth_client(
        client_id=provider_config.client_id,
        client_secret=provider_config.client_secret,
        scope=scope or provider_config.default_scope,
        redirect_uri=redirect_uri,
        token_endpoint_auth_method="client_secret_post",
    )


async def _fetch_provider_profile(
    *,
    provider: OAuthProvider,
    token: dict[str, Any],
    client: Any,
) -> dict[str, Any]:
    del token
    provider_config = _get_provider_config(provider)
    profile_response = await client.get(
        provider_config.userinfo_url,
        headers={"Accept": "application/json"},
    )
    profile_response.raise_for_status()
    profile = profile_response.json()
    if not isinstance(profile, dict):
        raise UnauthorizedError("OAuth provider returned an invalid profile payload")

    if provider == "github" and not profile.get("email"):
        emails_response = await client.get(
            settings.oauth_github_user_emails_url,
            headers={"Accept": "application/json"},
        )
        emails_response.raise_for_status()
        emails = emails_response.json()
        if isinstance(emails, list):
            for item in emails:
                if not isinstance(item, dict):
                    continue
                email_value = item.get("email")
                if not isinstance(email_value, str) or not email_value:
                    continue
                is_verified = bool(item.get("verified"))
                is_primary = bool(item.get("primary"))
                if is_verified and is_primary:
                    profile["email"] = email_value
                    break
            if not profile.get("email"):
                for item in emails:
                    if isinstance(item, dict) and isinstance(item.get("email"), str):
                        profile["email"] = item["email"]
                        break
    return profile


def _load_authlib_oauth_client() -> Any:
    try:
        from authlib.integrations.httpx_client import AsyncOAuth2Client
    except ModuleNotFoundError as exc:
        raise UnauthorizedError(
            "Authlib dependency is missing. "
            "Install project dependencies to enable OAuth providers.",
        ) from exc
    return AsyncOAuth2Client


async def _close_oauth_client(client: Any) -> None:
    close_method = getattr(client, "aclose", None) or getattr(client, "close", None)
    if close_method is None:
        return
    result = close_method()
    if hasattr(result, "__await__"):
        await result
