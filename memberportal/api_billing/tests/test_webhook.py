from unittest.mock import patch

from constance.test.unittest import override_config
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory
import stripe

from api_billing import views
from api_billing.models import ProcessedStripeEvent
from profile.models import Profile, User


class StripeWebhookTests(TestCase):
    def test_accepts_typed_invoice_for_unknown_customer(self):
        event = stripe.Event.construct_from(
            {
                "id": "evt_typed_invoice",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "id": "in_typed_invoice",
                        "object": "invoice",
                        "customer": "cus_unknown",
                    }
                },
            },
            None,
        )
        self.assertEqual(type(event["data"]["object"]).__name__, "Invoice")
        request = APIRequestFactory().post(
            "/api/billing/stripe-webhook/",
            data=b"signed-payload",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig_test",
        )

        with override_config(STRIPE_WEBHOOK_SECRET="whsec_test"):
            with patch.object(
                views.stripe.Webhook, "construct_event", return_value=event
            ) as construct_event:
                response = views.StripeWebhook.as_view()(request)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        construct_event.assert_called_once_with(
            payload=b"signed-payload",
            sig_header="sig_test",
            secret="whsec_test",
        )

    def test_processes_typed_invoice_for_matching_subscription(self):
        user = User.objects.create_user(
            "stripe-webhook@example.test", password="test-password"
        )
        profile = Profile.objects.create(
            user=user,
            first_name="Stripe",
            last_name="Member",
            state="active",
            subscription_status="active",
            stripe_customer_id="cus_test",
            stripe_subscription_id="sub_test",
        )
        event = stripe.Event.construct_from(
            {
                "id": "evt_matching_typed_invoice",
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "id": "in_matching_typed_invoice",
                        "object": "invoice",
                        "customer": "cus_test",
                        "status": "paid",
                        "parent": {
                            "subscription_details": {"subscription": "sub_test"}
                        },
                    }
                },
            },
            None,
        )
        request = APIRequestFactory().post(
            "/api/billing/stripe-webhook/",
            data=b"signed-payload",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig_test",
        )

        with override_config(STRIPE_WEBHOOK_SECRET="whsec_test"):
            with patch.object(
                views.stripe.Webhook, "construct_event", return_value=event
            ), patch.object(User, "log_event"):
                response = views.StripeWebhook.as_view()(request)

        profile.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(profile.subscription_first_created)
        self.assertTrue(
            ProcessedStripeEvent.objects.filter(
                event_id="evt_matching_typed_invoice"
            ).exists()
        )
