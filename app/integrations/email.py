"""Small provider-agnostic email adapter.

The configured endpoint is expected to accept a JSON payload with ``from``, ``to``, ``subject``,
``text`` and ``html`` fields. This keeps the application independent of a vendor SDK while still
providing timeouts, idempotency and retry/circuit-breaker behaviour through the shared client.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import UpstreamError
from app.integrations.http import ResilientHttpClient


@dataclass(frozen=True)
class EmailSendResult:
    status: str
    provider: str
    message_id: str | None = None


class EmailService:
    def __init__(
        self,
        *,
        client: ResilientHttpClient,
        provider: str,
        base_url: str | None,
        api_key: str | None,
        from_address: str,
        timeout_seconds: float,
    ) -> None:
        self._client = client
        self._provider = provider
        self._base_url = base_url.rstrip("/") if base_url else None
        self._api_key = api_key
        self._from = from_address
        self._timeout = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._api_key)

    async def send(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        html: str | None = None,
        idempotency_key: str | None = None,
    ) -> EmailSendResult:
        if not self.configured:
            return EmailSendResult(status="skipped", provider=self._provider)

        payload: dict[str, object] = {
            "from": self._from,
            "to": [to],
            "subject": subject,
            "text": text,
        }
        if html is not None:
            payload["html"] = html

        response = await self._client.request(
            "POST",
            self._base_url or "",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            idempotency_key=idempotency_key,
            breaker_name=f"email:{self._provider}",
            timeout=self._timeout,
        )
        if not 200 <= response.status_code < 300:
            detail = response.text[:500]
            raise UpstreamError(f"Email provider returned {response.status_code}: {detail}")

        message_id: str | None = None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if isinstance(body, dict):
            candidate = body.get("id") or body.get("message_id")
            if isinstance(candidate, str):
                message_id = candidate
        return EmailSendResult(status="sent", provider=self._provider, message_id=message_id)
