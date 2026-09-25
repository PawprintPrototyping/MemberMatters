import logging
import uuid

import stripe
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from sentry_sdk import capture_exception

from api_admin_tools.models import PaymentPlan
from profile.models import Profile

from .models import PaymentPlanSwitchOperation

logger = logging.getLogger("billing")
PRORATION_BEHAVIOR = "create_prorations"
MAX_RECOVERY_ATTEMPTS = 5


class PaymentPlanSwitchValidationError(Exception):
    def __init__(self, message, response_status=status.HTTP_409_CONFLICT):
        super().__init__(message)
        self.message = message
        self.response_status = response_status


def _stripe_value(resource, name, default=None):
    if isinstance(resource, dict):
        return resource.get(name, default)
    return getattr(resource, name, default)


def _subscription_items(subscription):
    items = _stripe_value(subscription, "items")
    return _stripe_value(items, "data", []) or []


def _price_id(item):
    price = _stripe_value(item, "price")
    if isinstance(price, str):
        return price
    return _stripe_value(price, "id")


def _price_signature(price):
    recurring = _stripe_value(price, "recurring") or {}
    return (
        _stripe_value(recurring, "interval"),
        _stripe_value(recurring, "interval_count"),
        str(_stripe_value(price, "currency", "")).lower(),
    )


def _local_signature(plan):
    return (plan.interval, plan.interval_count, plan.currency.lower())


def _error_response(message, response_status):
    return Response(
        {"success": False, "message": message},
        status=response_status,
    )


def _record_operation_error(operation_id, error):
    message = str(error)[:4000]
    try:
        with transaction.atomic():
            operation = PaymentPlanSwitchOperation.objects.select_for_update().get(
                pk=operation_id
            )
            operation.attempt_count += 1
            operation.last_error = message
            if operation.attempt_count >= MAX_RECOVERY_ATTEMPTS:
                operation.status = PaymentPlanSwitchOperation.STATUS_FAILED
            operation.save(update_fields=["attempt_count", "last_error", "status"])
    except Exception as record_error:
        capture_exception(record_error)
    return _error_response(
        "billing.planSwitchRecoveryPending",
        status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _discard_operation(operation_id):
    PaymentPlanSwitchOperation.objects.filter(pk=operation_id).delete()


def _apply_operation(operation_id):
    with transaction.atomic():
        operation = (
            PaymentPlanSwitchOperation.objects.select_for_update()
            .select_related("target_plan")
            .get(pk=operation_id)
        )
        profile = Profile.objects.select_for_update().get(pk=operation.profile_id)

        if profile.membership_plan_id == operation.target_plan_id:
            operation.delete()
            return operation.target_plan

        if (
            profile.membership_plan_id != operation.current_plan_id
            or profile.stripe_subscription_id != operation.stripe_subscription_id
        ):
            raise RuntimeError(
                "Profile changed while recovering payment plan switch "
                f"{operation_id}."
            )

        profile.membership_plan_id = operation.target_plan_id
        profile.save(update_fields=["membership_plan"])
        target_plan = operation.target_plan
        operation.delete()
        return target_plan


def process_payment_plan_switch(operation_id):
    """Complete or retry one durable payment-plan switch operation.

    Stripe idempotency makes retrying the same mutation safe after a lost
    response. If Stripe already has the target Price, only the local finalize
    transaction runs.
    """
    try:
        operation = PaymentPlanSwitchOperation.objects.select_related(
            "current_plan", "target_plan"
        ).get(pk=operation_id)
    except PaymentPlanSwitchOperation.DoesNotExist:
        return True

    try:
        subscription = stripe.Subscription.retrieve(operation.stripe_subscription_id)
        if _stripe_value(subscription, "status") != "active":
            raise PaymentPlanSwitchValidationError(
                "billing.planSwitchSubscriptionInactive"
            )

        items = _subscription_items(subscription)
        if len(items) != 1:
            raise PaymentPlanSwitchValidationError(
                "billing.planSwitchSubscriptionInvalid"
            )

        subscription_item = items[0]
        current_stripe_price_id = _price_id(subscription_item)
        if current_stripe_price_id == operation.target_plan.stripe_id:
            _apply_operation(operation_id)
            return True

        if current_stripe_price_id != operation.current_plan.stripe_id:
            raise PaymentPlanSwitchValidationError("billing.planSwitchOutOfSync")

        current_stripe_price = stripe.Price.retrieve(operation.current_plan.stripe_id)
        target_stripe_price = stripe.Price.retrieve(operation.target_plan.stripe_id)
        current_signature = _price_signature(current_stripe_price)
        target_signature = _price_signature(target_stripe_price)
        if (
            current_signature != _local_signature(operation.current_plan)
            or target_signature != _local_signature(operation.target_plan)
            or current_signature != target_signature
        ):
            raise PaymentPlanSwitchValidationError("billing.planSwitchPriceMismatch")

        modified_subscription = stripe.Subscription.modify(
            operation.stripe_subscription_id,
            items=[
                {
                    "id": _stripe_value(subscription_item, "id"),
                    "price": operation.target_plan.stripe_id,
                }
            ],
            proration_behavior=PRORATION_BEHAVIOR,
            idempotency_key=operation.idempotency_key,
        )
        modified_items = _subscription_items(modified_subscription)
        if (
            _stripe_value(modified_subscription, "status") != "active"
            or len(modified_items) != 1
            or _price_id(modified_items[0]) != operation.target_plan.stripe_id
        ):
            raise RuntimeError("Stripe did not confirm the requested plan switch.")

        _apply_operation(operation_id)
        return True
    except PaymentPlanSwitchValidationError as error:
        _discard_operation(operation_id)
        return error
    except stripe.error.StripeError as error:
        capture_exception(error)
        _record_operation_error(operation_id, error)
        return False
    except Exception as error:
        capture_exception(error)
        _record_operation_error(operation_id, error)
        return False


def switch_payment_plan(request):
    plan_id = request.data.get("planId")
    if not plan_id:
        return _error_response(
            "billing.planSwitchPlanRequired", status.HTTP_400_BAD_REQUEST
        )

    target_plan = get_object_or_404(
        PaymentPlan.objects.select_related("member_tier"),
        pk=plan_id,
        visible=True,
        member_tier__visible=True,
    )
    idempotency_token = request.headers.get("Idempotency-Key") or uuid.uuid4().hex
    idempotency_key = f"plan-switch-{request.user.profile.pk}-{idempotency_token[:200]}"

    with transaction.atomic():
        profile = Profile.objects.select_for_update().get(pk=request.user.profile.pk)
        existing_operation = PaymentPlanSwitchOperation.objects.filter(
            profile=profile
        ).first()
        if existing_operation:
            message = (
                "billing.planSwitchRecoveryFailed"
                if existing_operation.status == PaymentPlanSwitchOperation.STATUS_FAILED
                else "billing.planSwitchRecoveryPending"
            )
            return _error_response(message, status.HTTP_409_CONFLICT)

        if profile.state_locked:
            return _error_response("billing.stateLocked", status.HTTP_403_FORBIDDEN)
        if (
            profile.state != "active"
            or profile.subscription_status != "active"
            or not profile.membership_plan
            or not profile.stripe_subscription_id
        ):
            return _error_response(
                "billing.planSwitchActiveOnly", status.HTTP_409_CONFLICT
            )

        current_plan = profile.membership_plan
        if current_plan.pk == target_plan.pk:
            return _error_response(
                "billing.planSwitchSamePlan", status.HTTP_409_CONFLICT
            )
        if _local_signature(current_plan) != _local_signature(target_plan):
            return _error_response(
                "billing.planSwitchIntervalMismatch", status.HTTP_400_BAD_REQUEST
            )

        operation = PaymentPlanSwitchOperation.objects.create(
            profile=profile,
            current_plan=current_plan,
            target_plan=target_plan,
            stripe_subscription_id=profile.stripe_subscription_id,
            idempotency_key=idempotency_key,
        )

    result = process_payment_plan_switch(operation.pk)
    if result is True:
        return Response({"success": True, "plan": target_plan.get_object()})
    if isinstance(result, PaymentPlanSwitchValidationError):
        return _error_response(result.message, result.response_status)

    operation_status = (
        PaymentPlanSwitchOperation.objects.filter(pk=operation.pk)
        .values_list("status", flat=True)
        .first()
    )
    if operation_status == PaymentPlanSwitchOperation.STATUS_FAILED:
        return _error_response(
            "billing.planSwitchRecoveryFailed", status.HTTP_503_SERVICE_UNAVAILABLE
        )

    return _error_response(
        "billing.planSwitchRecoveryPending", status.HTTP_503_SERVICE_UNAVAILABLE
    )
