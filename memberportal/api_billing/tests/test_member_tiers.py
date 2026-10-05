from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from api_admin_tools.models import MemberTier, PaymentPlan
from profile.models import User


class MemberTiersTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(
            "member-tiers@example.test", password="test-password"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=user)

    def test_returns_only_visible_tiers_and_plans(self):
        visible_tier = MemberTier.objects.create(
            name="Standard",
            description="Standard membership",
            stripe_id="prod_standard",
        )
        PaymentPlan.objects.create(
            name="Monthly",
            description="Billed monthly",
            stripe_id="price_standard_monthly",
            member_tier=visible_tier,
            cost=5000,
            interval_count=1,
            interval="month",
        )
        PaymentPlan.objects.create(
            name="Hidden monthly",
            description="Hidden billing option",
            stripe_id="price_standard_hidden",
            member_tier=visible_tier,
            visible=False,
            cost=6000,
            interval_count=1,
            interval="month",
        )
        MemberTier.objects.create(
            name="Hidden",
            description="Hidden membership",
            stripe_id="prod_hidden",
            visible=False,
        )

        response = self.client.get("/api/billing/tiers/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            [
                {
                    "id": visible_tier.id,
                    "name": "Standard",
                    "description": "Standard membership",
                    "featured": False,
                    "plans": [
                        {
                            "id": visible_tier.plans.get(
                                stripe_id="price_standard_monthly"
                            ).id,
                            "name": "Monthly",
                            "description": "Billed monthly",
                            "currency": "aud",
                            "cost": 5000,
                            "intervalAmount": 1,
                            "interval": "month",
                        }
                    ],
                }
            ],
        )
