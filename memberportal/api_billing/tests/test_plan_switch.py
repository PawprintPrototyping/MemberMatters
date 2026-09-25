from types import SimpleNamespace
from unittest.mock import patch

import stripe
from django.test import TestCase
from rest_framework.test import APIClient

from api_admin_tools.models import MemberTier, PaymentPlan
from api_billing.models import PaymentPlanSwitchOperation
from api_billing.plan_switch import (
    MAX_RECOVERY_ATTEMPTS,
    _apply_operation,
    _price_id,
    _record_operation_error,
    _stripe_value,
    process_payment_plan_switch,
)
from profile.models import Profile, User

ORIGINAL_PROFILE_SAVE = Profile.save


class PaymentPlanSwitchTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            "plan-switch@example.test",
            password="test-password",
        )
        self.tier = MemberTier.objects.create(
            name="Standard",
            description="Standard membership",
            stripe_id="prod_standard",
        )
        self.current_plan = self.create_plan(
            name="Standard Monthly",
            stripe_id="price_standard_monthly",
        )
        self.target_plan = self.create_plan(
            name="Premium Monthly",
            stripe_id="price_premium_monthly",
        )
        self.profile = Profile.objects.create(
            user=self.user,
            first_name="Plan",
            last_name="Switcher",
            state="active",
            membership_plan=self.current_plan,
            stripe_customer_id="cus_plan_switch",
            stripe_subscription_id="sub_plan_switch",
            subscription_status="active",
            billing_method="card",
        )
        self.client.force_authenticate(self.user)

    def create_plan(self, name, stripe_id, **kwargs):
        return PaymentPlan.objects.create(
            name=name,
            description=name,
            stripe_id=stripe_id,
            member_tier=self.tier,
            currency="aud",
            cost=2000,
            interval_count=1,
            interval="month",
            **kwargs,
        )

    @staticmethod
    def subscription(price_id, status="active"):
        return SimpleNamespace(
            id="sub_plan_switch",
            status=status,
            items=SimpleNamespace(
                data=[
                    SimpleNamespace(
                        id="si_plan_switch",
                        price=SimpleNamespace(id=price_id),
                    )
                ]
            ),
        )

    @staticmethod
    def price(interval="month", interval_count=1, currency="aud"):
        return SimpleNamespace(
            active=True,
            currency=currency,
            recurring=SimpleNamespace(
                interval=interval,
                interval_count=interval_count,
            ),
        )

    def switch(self, **headers):
        return self.client.post(
            "/api/billing/myplan/switch/",
            {"planId": self.target_plan.pk},
            format="json",
            **headers,
        )

    def make_operation(self, status=PaymentPlanSwitchOperation.STATUS_PENDING):
        return PaymentPlanSwitchOperation.objects.create(
            profile=self.profile,
            current_plan=self.current_plan,
            target_plan=self.target_plan,
            stripe_subscription_id=self.profile.stripe_subscription_id,
            idempotency_key=f"plan-switch-helper-{self.profile.pk}-{status}",
            status=status,
        )

    def expected_error(self, request):
        with self.assertLogs("django.request", level="WARNING"):
            return request()

    @patch("api_billing.plan_switch.stripe.Price.retrieve")
    @patch("api_billing.plan_switch.stripe.Subscription.modify")
    @patch("api_billing.plan_switch.stripe.Subscription.retrieve")
    def test_switches_compatible_plan_on_existing_subscription(
        self, retrieve, modify, price_retrieve
    ):
        current_subscription = self.subscription(self.current_plan.stripe_id)
        updated_subscription = self.subscription(self.target_plan.stripe_id)
        retrieve.return_value = current_subscription
        modify.return_value = updated_subscription
        price_retrieve.side_effect = [self.price(), self.price()]

        response = self.switch(HTTP_IDEMPOTENCY_KEY="switch-test-key")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["success"])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.membership_plan_id, self.target_plan.pk)
        self.assertEqual(self.profile.stripe_subscription_id, "sub_plan_switch")
        self.assertEqual(self.profile.billing_method, "card")
        retrieve.assert_called_once_with("sub_plan_switch")
        modify.assert_called_once_with(
            "sub_plan_switch",
            items=[{"id": "si_plan_switch", "price": self.target_plan.stripe_id}],
            proration_behavior="create_prorations",
            idempotency_key=f"plan-switch-{self.profile.pk}-switch-test-key",
        )

    @patch("api_billing.plan_switch.stripe.Subscription.modify")
    @patch("api_billing.plan_switch.stripe.Subscription.retrieve")
    def test_rejects_interval_or_currency_mismatch_without_stripe_call(
        self, retrieve, modify
    ):
        for field, value in (
            ("interval", "year"),
            ("interval_count", 3),
            ("currency", "usd"),
        ):
            with self.subTest(field=field):
                setattr(self.target_plan, field, value)
                self.target_plan.save(update_fields=[field])

                response = self.expected_error(self.switch)

                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.data["message"], "billing.planSwitchIntervalMismatch"
                )
                retrieve.assert_not_called()
                modify.assert_not_called()

                setattr(self.target_plan, field, getattr(self.current_plan, field))
                self.target_plan.save(update_fields=[field])

    def test_rejects_non_active_subscription_states_without_stripe_call(self):
        for state in ("pending", "cancelling"):
            with self.subTest(state=state):
                self.profile.subscription_status = state
                self.profile.save(update_fields=["subscription_status"])

                with patch(
                    "api_billing.plan_switch.stripe.Subscription.retrieve"
                ) as retrieve:
                    response = self.expected_error(self.switch)

                self.assertEqual(response.status_code, 409)
                self.assertEqual(
                    response.data["message"], "billing.planSwitchActiveOnly"
                )
                retrieve.assert_not_called()

                self.profile.subscription_status = "active"
                self.profile.save(update_fields=["subscription_status"])

    @patch("api_billing.plan_switch.stripe.Price.retrieve")
    @patch("api_billing.plan_switch.stripe.Subscription.modify")
    @patch("api_billing.plan_switch.stripe.Subscription.retrieve")
    def test_stripe_failure_does_not_change_local_plan(
        self, retrieve, modify, price_retrieve
    ):
        retrieve.return_value = self.subscription(self.current_plan.stripe_id)
        price_retrieve.side_effect = [self.price(), self.price()]
        modify.side_effect = stripe.error.StripeError("plan switch failed")

        response = self.expected_error(self.switch)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["message"], "billing.planSwitchRecoveryPending")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.membership_plan_id, self.current_plan.pk)
        self.assertTrue(
            PaymentPlanSwitchOperation.objects.filter(profile=self.profile).exists()
        )

    @patch("profile.models.Profile.save", autospec=True)
    @patch("api_billing.plan_switch.stripe.Price.retrieve")
    @patch("api_billing.plan_switch.stripe.Subscription.modify")
    @patch("api_billing.plan_switch.stripe.Subscription.retrieve")
    def test_recovers_when_local_finalize_fails_after_stripe_success(
        self, retrieve, modify, price_retrieve, profile_save
    ):
        retrieve.return_value = self.subscription(self.current_plan.stripe_id)
        modify.return_value = self.subscription(self.target_plan.stripe_id)
        price_retrieve.side_effect = [self.price(), self.price()]

        save_calls = 0

        def fail_once(instance, *args, **kwargs):
            nonlocal save_calls
            if save_calls == 0:
                save_calls += 1
                raise RuntimeError("database unavailable")
            return ORIGINAL_PROFILE_SAVE(instance, *args, **kwargs)

        profile_save.side_effect = fail_once

        response = self.expected_error(self.switch)

        self.assertEqual(response.status_code, 503, response.data)
        operation = PaymentPlanSwitchOperation.objects.get(profile=self.profile)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.membership_plan_id, self.current_plan.pk)

        profile_save.side_effect = ORIGINAL_PROFILE_SAVE
        retrieve.return_value = self.subscription(self.target_plan.stripe_id)
        recovered = process_payment_plan_switch(operation.pk)
        if not recovered:
            self.fail(
                PaymentPlanSwitchOperation.objects.get(pk=operation.pk).last_error
            )
        self.assertTrue(recovered)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.membership_plan_id, self.target_plan.pk)
        self.assertFalse(
            PaymentPlanSwitchOperation.objects.filter(pk=operation.pk).exists()
        )

    @patch("api_billing.plan_switch.stripe.Price.retrieve")
    @patch("api_billing.plan_switch.stripe.Subscription.retrieve")
    def test_rejects_subscription_that_is_not_active_in_stripe(
        self, retrieve, price_retrieve
    ):
        retrieve.return_value = self.subscription(
            self.current_plan.stripe_id, status="past_due"
        )

        response = self.expected_error(self.switch)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.data["message"], "billing.planSwitchSubscriptionInactive"
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.membership_plan_id, self.current_plan.pk)

    def test_rejects_plan_under_hidden_tier(self):
        hidden_tier = MemberTier.objects.create(
            name="Hidden",
            description="Hidden membership",
            stripe_id="prod_hidden",
            visible=False,
        )
        hidden_plan = PaymentPlan.objects.create(
            name="Hidden Monthly",
            description="Hidden Monthly",
            stripe_id="price_hidden_monthly",
            member_tier=hidden_tier,
            currency="aud",
            cost=2000,
            interval_count=1,
            interval="month",
            visible=True,
        )

        response = self.expected_error(
            lambda: self.client.post(
                "/api/billing/myplan/switch/",
                {"planId": hidden_plan.pk},
                format="json",
            )
        )

        self.assertEqual(response.status_code, 404)

    @patch("api_billing.plan_switch.stripe.Price.retrieve")
    @patch("api_billing.plan_switch.stripe.Subscription.modify")
    @patch("api_billing.plan_switch.stripe.Subscription.retrieve")
    def test_rejects_stale_stripe_price_metadata(
        self, retrieve, modify, price_retrieve
    ):
        retrieve.return_value = self.subscription(self.current_plan.stripe_id)
        price_retrieve.side_effect = [self.price(), self.price(interval="year")]

        response = self.expected_error(self.switch)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["message"], "billing.planSwitchPriceMismatch")
        modify.assert_not_called()

    @patch("api_billing.plan_switch.stripe.Price.retrieve")
    @patch("api_billing.plan_switch.stripe.Subscription.modify")
    @patch("api_billing.plan_switch.stripe.Subscription.retrieve")
    def test_marks_operation_failed_after_bounded_recovery_attempts(
        self, retrieve, modify, price_retrieve
    ):
        retrieve.return_value = self.subscription(self.current_plan.stripe_id)
        price_retrieve.return_value = self.price()
        modify.side_effect = stripe.error.StripeError("permanent Stripe failure")

        response = self.expected_error(self.switch)
        self.assertEqual(response.status_code, 503)
        operation = PaymentPlanSwitchOperation.objects.get(profile=self.profile)

        for _ in range(MAX_RECOVERY_ATTEMPTS - 1):
            self.assertFalse(process_payment_plan_switch(operation.pk))

        operation.refresh_from_db()
        self.assertEqual(operation.status, PaymentPlanSwitchOperation.STATUS_FAILED)
        self.assertEqual(operation.attempt_count, MAX_RECOVERY_ATTEMPTS)

        blocked_response = self.expected_error(self.switch)
        self.assertEqual(blocked_response.status_code, 409)
        self.assertEqual(
            blocked_response.data["message"], "billing.planSwitchRecoveryFailed"
        )

    def test_stripe_helpers_accept_dict_and_string_objects(self):
        self.assertEqual(_stripe_value({"id": "price_1"}, "id"), "price_1")
        self.assertEqual(_price_id({"price": "price_1"}), "price_1")

    def test_process_missing_operation_is_already_complete(self):
        self.assertTrue(process_payment_plan_switch(999999))

    def test_apply_operation_is_idempotent_when_profile_already_target(self):
        operation = self.make_operation()
        self.profile.membership_plan = self.target_plan
        self.profile.save(update_fields=["membership_plan"])

        result = _apply_operation(operation.pk)

        self.assertEqual(result.pk, self.target_plan.pk)
        self.assertFalse(
            PaymentPlanSwitchOperation.objects.filter(pk=operation.pk).exists()
        )

    def test_apply_operation_rejects_profile_drift(self):
        operation = self.make_operation()
        self.profile.stripe_subscription_id = "sub_changed"
        self.profile.save(update_fields=["stripe_subscription_id"])

        with self.assertRaisesMessage(RuntimeError, "Profile changed"):
            _apply_operation(operation.pk)

        self.assertTrue(
            PaymentPlanSwitchOperation.objects.filter(pk=operation.pk).exists()
        )

    @patch("api_billing.plan_switch.capture_exception")
    @patch("api_billing.plan_switch.PaymentPlanSwitchOperation.save")
    def test_record_operation_error_tolerates_database_failure(
        self, save, capture_exception
    ):
        operation = self.make_operation()
        save.side_effect = RuntimeError("database unavailable")

        response = _record_operation_error(operation.pk, RuntimeError("stripe"))

        self.assertEqual(response.status_code, 503)
        capture_exception.assert_called_once()

    @patch("api_billing.plan_switch.stripe.Price.retrieve")
    @patch("api_billing.plan_switch.stripe.Subscription.modify")
    @patch("api_billing.plan_switch.stripe.Subscription.retrieve")
    def test_unconfirmed_stripe_update_is_retried(
        self, retrieve, modify, price_retrieve
    ):
        operation = self.make_operation()
        retrieve.return_value = self.subscription(self.current_plan.stripe_id)
        price_retrieve.return_value = self.price()
        modify.return_value = self.subscription(self.current_plan.stripe_id)

        self.assertFalse(process_payment_plan_switch(operation.pk))
        operation.refresh_from_db()
        self.assertEqual(operation.attempt_count, 1)
        self.assertEqual(operation.status, PaymentPlanSwitchOperation.STATUS_PENDING)

    def test_switch_rejects_missing_plan_id(self):
        response = self.expected_error(
            lambda: self.client.post("/api/billing/myplan/switch/", {}, format="json")
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "billing.planSwitchPlanRequired")

    def test_switch_rejects_locked_member(self):
        self.profile.state_locked = True
        self.profile.save(update_fields=["state_locked"])

        response = self.expected_error(self.switch)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["message"], "billing.stateLocked")

    def test_switch_rejects_same_plan(self):
        response = self.expected_error(
            lambda: self.client.post(
                "/api/billing/myplan/switch/",
                {"planId": self.current_plan.pk},
                format="json",
            )
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["message"], "billing.planSwitchSamePlan")

    def test_switch_rejects_existing_pending_and_failed_operations(self):
        pending = self.make_operation()
        pending_response = self.expected_error(self.switch)
        self.assertEqual(pending_response.status_code, 409)
        self.assertEqual(
            pending_response.data["message"], "billing.planSwitchRecoveryPending"
        )

        pending.delete()
        self.make_operation(status=PaymentPlanSwitchOperation.STATUS_FAILED)
        failed_response = self.expected_error(self.switch)
        self.assertEqual(failed_response.status_code, 409)
        self.assertEqual(
            failed_response.data["message"], "billing.planSwitchRecoveryFailed"
        )

    @patch("api_billing.plan_switch.stripe.Subscription.retrieve")
    def test_process_rejects_unexpected_subscription_item_count(self, retrieve):
        operation = self.make_operation()
        retrieve.return_value = SimpleNamespace(
            status="active", items=SimpleNamespace(data=[])
        )

        result = process_payment_plan_switch(operation.pk)

        self.assertIsInstance(result, Exception)
        self.assertEqual(result.message, "billing.planSwitchSubscriptionInvalid")
        self.assertFalse(
            PaymentPlanSwitchOperation.objects.filter(pk=operation.pk).exists()
        )

    @patch("api_billing.plan_switch.stripe.Subscription.retrieve")
    def test_process_rejects_unexpected_current_stripe_price(self, retrieve):
        operation = self.make_operation()
        retrieve.return_value = self.subscription("price_unexpected")

        result = process_payment_plan_switch(operation.pk)

        self.assertIsInstance(result, Exception)
        self.assertEqual(result.message, "billing.planSwitchOutOfSync")
        self.assertFalse(
            PaymentPlanSwitchOperation.objects.filter(pk=operation.pk).exists()
        )

    @patch("api_billing.plan_switch.process_payment_plan_switch")
    def test_switch_reports_terminal_recovery_failure(self, process):
        def fail_and_mark_failed(operation_id):
            PaymentPlanSwitchOperation.objects.filter(pk=operation_id).update(
                status=PaymentPlanSwitchOperation.STATUS_FAILED
            )
            return False

        process.side_effect = fail_and_mark_failed
        response = self.expected_error(self.switch)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["message"], "billing.planSwitchRecoveryFailed")
