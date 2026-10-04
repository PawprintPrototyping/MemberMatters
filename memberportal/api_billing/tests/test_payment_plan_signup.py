from types import SimpleNamespace
from unittest.mock import patch

from constance.test.unittest import override_config
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from api_admin_tools.models import MemberTier, PaymentPlan
from api_billing.views import PaymentPlanSignup
from profile.models import Profile, SignupTriggeredBy, SubscriptionState, User


class PaymentPlanSignupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "initial-signup@example.test", password="test-password"
        )
        self.profile = Profile.objects.create(
            user=self.user,
            first_name="Initial",
            last_name="Signup",
        )
        tier = MemberTier.objects.create(
            name="Standard",
            description="Standard membership",
            stripe_id="prod_standard",
        )
        self.plan = PaymentPlan.objects.create(
            name="Monthly",
            description="Billed monthly",
            stripe_id="price_standard_monthly",
            member_tier=tier,
            cost=5000,
            interval_count=1,
            interval="month",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @override_config(ENABLE_NEW_SUBSCRIPTIONS=True)
    @patch.object(Profile, "complete_signup")
    @patch.object(PaymentPlanSignup, "create_subscription")
    def test_initial_card_signup_persists_active_subscription(
        self, create_subscription, complete_signup
    ):
        create_subscription.return_value = (
            SimpleNamespace(id="sub_initial", status=SubscriptionState.ACTIVE),
            None,
        )

        response = self.client.post(
            f"/api/billing/plans/{self.plan.id}/signup/",
            {"billingMethod": "card"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True})
        create_subscription.assert_called_once()
        complete_signup.assert_called_once_with(SignupTriggeredBy.SUBSCRIPTION_CREATED)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.stripe_subscription_id, "sub_initial")
        self.assertEqual(self.profile.membership_plan_id, self.plan.id)
        self.assertEqual(self.profile.subscription_status, SubscriptionState.ACTIVE)
        self.assertEqual(self.profile.billing_method, "card")
