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


class PaymentPlanResumeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "resume-member@example.test", password="test-password"
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
        self.profile = Profile.objects.create(
            user=self.user,
            first_name="Resume",
            last_name="Member",
            state="active",
            membership_plan=self.plan,
            stripe_subscription_id="sub_cancelling",
            subscription_status=SubscriptionState.CANCELLING,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_unauthenticated_resume_is_denied(self):
        response = APIClient().post("/api/billing/myplan/resume/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_resume_without_membership_plan_returns_not_found(self):
        self.profile.membership_plan = None
        self.profile.save(update_fields=["membership_plan"])

        response = self.client.post("/api/billing/myplan/resume/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            response.json(),
            {"success": False, "message": "paymentPlan.notExists"},
        )

    @patch("api_billing.views.stripe.Subscription.modify")
    def test_resume_cancelling_membership_plan(self, modify_subscription):
        modify_subscription.return_value = SimpleNamespace(cancel_at_period_end=False)

        response = self.client.post("/api/billing/myplan/resume/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True})
        modify_subscription.assert_called_once_with(
            "sub_cancelling", cancel_at_period_end=False
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.subscription_status, SubscriptionState.ACTIVE)
