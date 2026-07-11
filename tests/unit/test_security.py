from __future__ import annotations

import pytest

from app.core.errors import UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    require_api_key,
    resolve_api_key,
)

pytestmark = pytest.mark.unit


def test_access_token_round_trip_preserves_identity_and_scopes() -> None:
    token, expires_in = create_access_token(
        user_id=42,
        scopes=["tasks:read", "tasks:write"],
        is_admin=False,
        subject="user@taskflow.dev",
    )

    claims = decode_access_token(token)

    assert expires_in > 0
    assert claims["uid"] == 42
    assert claims["scope"] == "tasks:read tasks:write"


def test_refresh_token_round_trip_and_access_type_validation() -> None:
    refresh_token, expires_in = create_refresh_token(
        user_id=42,
        subject="user@taskflow.dev",
        session_id="session-1",
    )

    claims = decode_refresh_token(refresh_token)

    assert expires_in > 0
    assert claims["uid"] == 42
    with pytest.raises(UnauthorizedError, match="Invalid refresh token type"):
        decode_refresh_token(create_access_token(
            user_id=42,
            scopes=["tasks:read"],
            is_admin=False,
            subject="user@taskflow.dev",
        )[0])


def test_api_key_resolution_exposes_fingerprint_and_scopes() -> None:
    principal = resolve_api_key("local-dev-key")

    assert principal is not None
    assert len(principal.key_id) == 12
    assert "tasks:read" in principal.scopes
    assert resolve_api_key("missing-key") is None


@pytest.mark.asyncio
async def test_api_key_requirement_rejects_missing_and_accepts_configured_key() -> None:
    with pytest.raises(UnauthorizedError, match="Invalid API key"):
        await require_api_key(None)

    assert await require_api_key("local-dev-key") == "local-dev-key"
