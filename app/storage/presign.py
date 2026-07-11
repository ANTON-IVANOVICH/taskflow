"""HMAC-signed upload tokens for the local storage backend.

They stand in for S3 presigned POST policies: the token carries the target key, the permitted
content type, a max size, and an expiry, all signed so a client can't tamper with them. The app
verifies the token on the ``PUT`` receiver endpoint before accepting bytes.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time

from app.core.errors import InvalidSignature


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def sign_upload_token(
    *,
    secret: str,
    key: str,
    content_type: str,
    max_size: int,
    expires_at: int,
) -> str:
    payload = {
        "key": key,
        "content_type": content_type,
        "max_size": max_size,
        "exp": expires_at,
    }
    payload_segment = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(secret.encode(), payload_segment.encode(), hashlib.sha256).digest()
    return f"{payload_segment}.{_b64url_encode(signature)}"


def verify_upload_token(*, secret: str, token: str) -> dict[str, object]:
    try:
        payload_segment, signature_segment = token.split(".")
        provided_signature = _b64url_decode(signature_segment)
        payload_value = json.loads(_b64url_decode(payload_segment))
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise InvalidSignature("Malformed upload token") from exc

    expected = hmac.new(secret.encode(), payload_segment.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(provided_signature, expected):
        raise InvalidSignature("Upload token signature mismatch")

    if not isinstance(payload_value, dict):
        raise InvalidSignature("Malformed upload token payload")
    payload: dict[str, object] = payload_value
    exp = payload.get("exp")
    if not isinstance(exp, int) or int(time.time()) >= exp:
        raise InvalidSignature("Upload token expired")
    return payload
