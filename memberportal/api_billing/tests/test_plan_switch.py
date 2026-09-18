from types import SimpleNamespace
from unittest.mock import patch

import stripe
from django.test import TestCase
from rest_framework.test import APIClient

from api_admin_tools.models import MemberTier, PaymentPlan
from profile.models import Profile, User


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

    def switch(self, **headers):
        return self.client.post(
            "/api/billing/myplan/switch/",
            {"planId": self.target_plan.pk},
            format="json",
            **headers,
        )

    @patch("api_billing.views.stripe.Subscription.modify")
    @patch("api_billing.views.stripe.Subscription.retrieve")
    def test_switches_compatible_plan_on_existing_subscription(self, retrieve, modify):
        current_subscription = self.subscription(self.current_plan.stripe_id)
        updated_subscription = self.subscription(self.target_plan.stripe_id)
        retrieve.return_value = current_subscription
        modify.return_value = updated_subscription

        response = self.switch(HTTP_IDEMPOTENCY_KEY="switch-test-key")

        self.assertEqual(response.status_code, 200)
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

    @patch("api_billing.views.stripe.Subscription.modify")
    @patch("api_billing.views.stripe.Subscription.retrieve")
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

                response = self.switch()

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
                    "api_billing.views.stripe.Subscription.retrieve"
                ) as retrieve:
                    response = self.switch()

                self.assertEqual(response.status_code, 409)
                self.assertEqual(
                    response.data["message"], "billing.planSwitchActiveOnly"
                )
                retrieve.assert_not_called()

                self.profile.subscription_status = "active"
                self.profile.save(update_fields=["subscription_status"])

    @patch("api_billing.views.stripe.Subscription.modify")
    @patch("api_billing.views.stripe.Subscription.retrieve")
    def test_stripe_failure_does_not_change_local_plan(self, retrieve, modify):
        retrieve.return_value = self.subscription(self.current_plan.stripe_id)
        modify.side_effect = stripe.error.StripeError("plan switch failed")

        response = self.switch()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["message"], "billing.stripeError")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.membership_plan_id, self.current_plan.pk)

    @patch("api_billing.views.stripe.Subscription.retrieve")
    def test_rejects_subscription_that_is_not_active_in_stripe(self, retrieve):
        retrieve.return_value = self.subscription(
            self.current_plan.stripe_id, status="past_due"
        )

        response = self.switch()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.data["message"], "billing.planSwitchSubscriptionInactive"
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.membership_plan_id, self.current_plan.pk)
