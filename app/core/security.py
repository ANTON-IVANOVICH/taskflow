from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Security
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer

from app.core.config import get_settings
from app.core.errors import UnauthorizedError

SUPPORTED_SCOPES: dict[str, str] = {
    "tasks:read": "Read tasks",
    "tasks:write": "Create and update tasks",
    "teams:read": "Read teams",
    "integrations:write": "Import tasks from external systems",
    "admin": "Admin-only operations",
}

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/users/token",
    scopes=SUPPORTED_SCOPES,
    auto_error=False,
)

api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass(frozen=True)
class ApiKeyPrincipal:
    key_id: str
    scopes: set[str]


def now_utc_ts() -> int:
    return int(time.time())


def create_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def create_access_token(
    *,
    user_id: int,
    scopes: list[str],
    is_admin: bool,
    subject: str,
) -> tuple[str, int]:
    settings = get_settings()
    issued_at = now_utc_ts()
    expires_in = settings.access_token_ttl_seconds
    payload = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": subject,
        "uid": user_id,
        "scope": " ".join(scopes),
        "is_admin": is_admin,
        "type": "access",
        "iat": issued_at,
        "nbf": issued_at,
        "exp": issued_at + expires_in,
        "jti": secrets.token_urlsafe(16),
    }
    return encode_jwt(payload), expires_in


def create_refresh_token(
    *,
    user_id: int,
    subject: str,
    session_id: str,
) -> tuple[str, int]:
    settings = get_settings()
    issued_at = now_utc_ts()
    expires_in = settings.refresh_token_ttl_seconds
    payload = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": subject,
        "uid": user_id,
        "sid": session_id,
        "type": "refresh",
        "iat": issued_at,
        "nbf": issued_at,
        "exp": issued_at + expires_in,
        "jti": secrets.token_urlsafe(16),
    }
    return encode_jwt(payload), expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    payload = decode_jwt(token)
    token_type = payload.get("type")
    if token_type != "access":
        raise UnauthorizedError("Invalid access token type")
    return payload


def decode_refresh_token(token: str) -> dict[str, Any]:
    payload = decode_jwt(token)
    token_type = payload.get("type")
    if token_type != "refresh":
        raise UnauthorizedError("Invalid refresh token type")
    return payload


def encode_jwt(payload: dict[str, Any]) -> str:
    settings = get_settings()
    header = {"alg": "HS256", "typ": "JWT"}
    header_segment = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_segment = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_segment}.{payload_segment}".encode()
    signature = hmac.new(
        settings.jwt_secret_key.encode(),
        signing_input,
        digestmod=hashlib.sha256,
    ).digest()
    signature_segment = _b64url_encode(signature)
    return f"{header_segment}.{payload_segment}.{signature_segment}"


def decode_jwt(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        header_segment, payload_segment, signature_segment = token.split(".")
    except ValueError as exc:
        raise UnauthorizedError("Invalid token format") from exc

    signing_input = f"{header_segment}.{payload_segment}".encode()
    expected_signature = hmac.new(
        settings.jwt_secret_key.encode(),
        signing_input,
        digestmod=hashlib.sha256,
    ).digest()
    actual_signature = _b64url_decode(signature_segment)
    if not hmac.compare_digest(actual_signature, expected_signature):
        raise UnauthorizedError("Invalid token signature")

    try:
        header = json.loads(_b64url_decode(header_segment))
        payload = json.loads(_b64url_decode(payload_segment))
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
        raise UnauthorizedError("Invalid token payload") from exc

    if header.get("alg") != "HS256":
        raise UnauthorizedError("Unsupported token algorithm")
    if header.get("typ") != "JWT":
        raise UnauthorizedError("Unsupported token type header")

    now = now_utc_ts()
    exp = payload.get("exp")
    nbf = payload.get("nbf")
    iss = payload.get("iss")
    aud = payload.get("aud")

    if not isinstance(exp, int) or now >= exp:
        raise UnauthorizedError("Token expired")
    if not isinstance(nbf, int) or now < nbf:
        raise UnauthorizedError("Token is not valid yet")
    if iss != settings.jwt_issuer:
        raise UnauthorizedError("Invalid token issuer")
    if aud != settings.jwt_audience:
        raise UnauthorizedError("Invalid token audience")

    return payload


def resolve_api_key(api_key: str | None) -> ApiKeyPrincipal | None:
    if api_key is None:
        return None
    profile = _machine_api_key_profiles().get(api_key)
    if profile is None:
        return None
    return ApiKeyPrincipal(key_id=_key_fingerprint(api_key), scopes=set(profile))


async def require_api_key(
    api_key: Annotated[str | None, Security(api_key_scheme)],
) -> str:
    principal = resolve_api_key(api_key)
    if principal is None:
        raise UnauthorizedError("Invalid API key")
    return api_key or ""


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _key_fingerprint(api_key: str) -> str:
    digest = hashlib.sha256(api_key.encode()).hexdigest()
    return digest[:12]


@lru_cache
def _machine_api_key_profiles() -> dict[str, set[str]]:
    raw_value = get_settings().machine_api_keys
    profiles: dict[str, set[str]] = {}
    for pair in raw_value.split(";"):
        pair = pair.strip()
        if not pair:
            continue
        key, separator, scopes_raw = pair.partition("=")
        if not separator:
            continue
        key = key.strip()
        if not key:
            continue
        scopes = {
            scope.strip()
            for scope in scopes_raw.split(",")
            if scope.strip()
        }
        profiles[key] = scopes
    return profiles
