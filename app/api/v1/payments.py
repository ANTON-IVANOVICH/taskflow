from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Body, Path, Request, status
from sqlalchemy.exc import IntegrityError

from app.core.deps import IntegrationsWriter, UoWDep
from app.core.errors import PaymentNotFound, PermissionDenied
from app.db.models import Payment
from app.integrations.runtime import get_stripe_service
from app.schemas.payments import (
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    PaymentStatusResponse,
)

router = APIRouter(prefix="/payments", tags=["payments"])


def _to_checkout_response(payment: Payment) -> CheckoutSessionResponse:
    return CheckoutSessionResponse(
        id=payment.id,
        provider=payment.provider,
        external_id=payment.external_id or "",
        status=payment.status,
        checkout_url=payment.checkout_url,
        amount=payment.amount,
        currency=payment.currency,
        idempotency_key=payment.idempotency_key,
    )


@router.post(
    "/checkout",
    response_model=CheckoutSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an idempotent Stripe Checkout Session",
)
async def create_checkout_session(
    payload: Annotated[CheckoutSessionRequest, Body()],
    current_user: IntegrationsWriter,
    request: Request,
    uow: UoWDep,
) -> CheckoutSessionResponse:
    idempotency_key = payload.idempotency_key or f"tf_{current_user.id}_{uuid4().hex}"
    existing = await uow.payments.get_by_idempotency_key(
        provider="stripe",
        key=idempotency_key,
    )
    if existing is not None:
        return _to_checkout_response(existing)

    stripe = get_stripe_service(request.app)
    session = await stripe.create_checkout_session(
        amount=payload.amount,
        currency=payload.currency.lower(),
        description=payload.description,
        success_url=payload.success_url,
        cancel_url=payload.cancel_url,
        customer_email=str(current_user.email),
        idempotency_key=idempotency_key,
    )
    try:
        payment = await uow.payments.create(
            provider="stripe",
            external_id=session.external_id,
            idempotency_key=idempotency_key,
            customer_email=str(current_user.email),
            description=payload.description,
            amount=payload.amount,
            currency=payload.currency.lower(),
            status="pending",
            checkout_url=session.checkout_url,
            payment_metadata={"stripe_status": session.status},
        )
        await uow.commit()
    except IntegrityError:
        # Concurrent callers can use the same idempotency key. Let the database unique index
        # arbitrate, then return the committed record rather than creating a duplicate response.
        await uow.rollback()
        payment = await uow.payments.get_by_idempotency_key(
            provider="stripe",
            key=idempotency_key,
        )
        if payment is None:
            payment = await uow.payments.get_by_external_id(
                provider="stripe",
                external_id=session.external_id,
            )
        if payment is None:
            raise
    return _to_checkout_response(payment)


@router.get(
    "/{payment_id}",
    response_model=PaymentStatusResponse,
    summary="Get the local status of a payment",
)
async def get_payment_status(
    payment_id: Annotated[int, Path(ge=1)],
    current_user: IntegrationsWriter,
    uow: UoWDep,
) -> PaymentStatusResponse:
    payment = await uow.payments.get(payment_id)
    if payment is None:
        raise PaymentNotFound(payment_id)
    if not current_user.is_admin and payment.customer_email != str(current_user.email):
        raise PermissionDenied("You do not have access to this payment")
    return PaymentStatusResponse(
        id=payment.id,
        provider=payment.provider,
        external_id=payment.external_id,
        status=payment.status,
        amount=payment.amount,
        currency=payment.currency,
        checkout_url=payment.checkout_url,
    )
