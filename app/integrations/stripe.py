"""Raw HTTP adapter for Stripe Checkout Sessions.

Stripe's API is form-encoded, so this module deliberately uses the shared resilient HTTP client
instead of adding another SDK. The idempotency key makes a retried POST safe.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import IntegrationNotConfigured, UpstreamError
from app.integrations.http import ResilientHttpClient


@dataclass(frozen=True)
class StripeCheckoutSession:
    external_id: str
    status: str
    checkout_url: str | None


class StripeService:
    def __init__(
        self,
        *,
        client: ResilientHttpClient,
        api_key: str | None,
        base_url: str,
        timeout_seconds: float,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def create_checkout_session(
        self,
        *,
        amount: int,
        currency: str,
        description: str,
        success_url: str,
        cancel_url: str,
        customer_email: str | None,
        idempotency_key: str,
    ) -> StripeCheckoutSession:
        if not self.configured:
            raise IntegrationNotConfigured("stripe")

        form: dict[str, str] = {
            "mode": "payment",
            "line_items[0][price_data][currency]": currency.lower(),
            "line_items[0][price_data][product_data][name]": description,
            "line_items[0][price_data][unit_amount]": str(amount),
            "line_items[0][quantity]": "1",
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
        if customer_email:
            form["customer_email"] = customer_email

        response = await self._client.request(
            "POST",
            f"{self._base_url}/v1/checkout/sessions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            data=form,
            idempotency_key=idempotency_key,
            breaker_name="stripe",
            timeout=self._timeout,
        )
        if not 200 <= response.status_code < 300:
            raise UpstreamError(f"Stripe returned {response.status_code}: {response.text[:500]}")

        try:
            body = response.json()
        except ValueError as exc:
            raise UpstreamError("Stripe returned invalid JSON") from exc
        if not isinstance(body, dict) or not isinstance(body.get("id"), str):
            raise UpstreamError("Stripe response did not contain a checkout session id")

        raw_status = body.get("status")
        status = raw_status if isinstance(raw_status, str) else "open"
        raw_url = body.get("url")
        checkout_url = raw_url if isinstance(raw_url, str) else None
        return StripeCheckoutSession(
            external_id=body["id"],
            status=status,
            checkout_url=checkout_url,
        )
