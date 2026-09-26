from types import SimpleNamespace
from unittest.mock import Mock, patch

from constance.test.unittest import override_config
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory

from api_billing import views
from api_billing.models import ProcessedStripeEvent
from profile.models import Profile, User


class StripeWebhookTests(TestCase):
    webhook_config = {
        "STRIPE_WEBHOOK_SECRET": "whsec_test",
        "ENABLE_STRIPE_MEMBERSHIP_PAYMENTS": True,
        "TERMS_ACCEPTANCE_CARDS": "[]",
        "REQUIRE_ACCESS_CARD": False,
        "CANVAS_INDUCTION_ENABLED": False,
        "MOODLE_INDUCTION_ENABLED": False,
        "ENABLE_DOCUSEAL_INTEGRATION": False,
    }

    def make_profile(
        self,
        *,
        state="noob",
        subscription_status="pending",
        customer_id="cus_test",
        subscription_id="sub_test",
        state_locked=False,
    ):
        suffix = Profile.objects.count() + 1
        user = User.objects.create_user(
            f"stripe-webhook-{suffix}@example.test",
            password="test-password",
        )
        return Profile.objects.create(
            user=user,
            first_name="Stripe",
            last_name=str(suffix),
            state=state,
            state_locked=state_locked,
            subscription_status=subscription_status,
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
        )

    def make_event(self, event_type="invoice.paid", **data):
        return {
            "id": data.pop("event_id", "evt_test"),
            "type": event_type,
            "data": {
                "object": {
                    "customer": "cus_test",
                    "subscription": "sub_test",
                    "status": "paid",
                    **data,
                }
            },
        }

    def post_event(self, event):
        request = APIRequestFactory().post(
            "/api/billing/stripe-webhook/",
            data=b"signed-payload",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig_test",
        )
        with patch.object(
            views.stripe.Webhook,
            "construct_event",
            return_value=event,
        ):
            return views.StripeWebhook.as_view()(request)

    def test_rejects_events_without_a_signing_secret(self):
        with override_config(STRIPE_WEBHOOK_SECRET=""):
            with patch.object(views.stripe.Webhook, "construct_event") as construct:
                response = self.post_event(self.make_event())

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data, {"error": "Webhook signing not configured."})
        construct.assert_not_called()

    def test_reports_signature_validation_failures(self):
        error = ValueError("bad signature")
        request = APIRequestFactory().post(
            "/api/billing/stripe-webhook/",
            data=b"invalid-payload",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig_test",
        )
        with override_config(**self.webhook_config):
            with patch.object(
                views.stripe.Webhook,
                "construct_event",
                side_effect=error,
            ), patch.object(views, "capture_exception") as capture:
                response = views.StripeWebhook.as_view()(request)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {"error": "Error validating Stripe signature."},
        )
        capture.assert_called_once_with(error)

    def test_ignores_events_without_a_customer(self):
        event = self.make_event(customer=None)

        with override_config(**self.webhook_config):
            with patch.object(views.Profile.objects, "get") as profile_get:
                response = self.post_event(event)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        profile_get.assert_not_called()

    def test_accepts_new_invoice_subscription_schema_and_deduplicates(self):
        self.make_profile()
        event = self.make_event(
            parent={"subscription_details": {"subscription": "sub_test"}},
            subscription=None,
            event_id="evt_nested_subscription",
        )

        with override_config(**self.webhook_config):
            with patch.object(views.StripeWebhook, "_handle_event") as handle:
                first_response = self.post_event(event)
                second_response = self.post_event(event)

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        handle.assert_called_once()
        self.assertEqual(
            ProcessedStripeEvent.objects.filter(
                event_id="evt_nested_subscription"
            ).count(),
            1,
        )

    def test_ignores_out_of_scope_invoice_without_claiming_event(self):
        self.make_profile()
        event = self.make_event(
            subscription="sub_other",
            event_id="evt_out_of_scope",
        )

        with override_config(**self.webhook_config):
            with patch.object(views.StripeWebhook, "_handle_event") as handle:
                response = self.post_event(event)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        handle.assert_not_called()
        self.assertFalse(
            ProcessedStripeEvent.objects.filter(event_id="evt_out_of_scope").exists()
        )

    def test_paid_invoice_activates_member_and_continues_after_email_failure(self):
        profile = self.make_profile()
        event = self.make_event(event_id="evt_paid_activation")

        with override_config(**self.webhook_config):
            with patch.object(
                Profile,
                "can_signup",
                return_value={"success": True},
            ), patch.object(
                Profile, "complete_signup"
            ) as complete_signup, patch.object(
                User,
                "log_event",
            ), patch.object(
                User,
                "email_notification",
                side_effect=RuntimeError("email unavailable"),
            ), patch.object(
                views, "send_email_to_admin"
            ) as send_admin, patch.object(
                views,
                "capture_exception",
            ) as capture:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.post_event(event)

        profile.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(profile.subscription_status, "active")
        self.assertIsNotNone(profile.subscription_first_created)
        complete_signup.assert_called_once()
        send_admin.assert_not_called()
        capture.assert_called_once()

    def test_paid_invoice_holds_state_locked_member(self):
        profile = self.make_profile(state_locked=True)
        event = self.make_event(event_id="evt_locked_paid")

        with override_config(**self.webhook_config):
            with patch.object(User, "log_event"), patch.object(
                views,
                "send_email_to_admin",
            ) as send_admin:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.post_event(event)

        profile.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(profile.subscription_status, "pending")
        send_admin.assert_called_once()
        self.assertIn("locked member", send_admin.call_args.kwargs["subject"])

    def test_paid_invoice_marks_ineligible_member_active_and_notifies_admin(self):
        profile = self.make_profile(state="accountonly")
        event = self.make_event(event_id="evt_paid_ineligible")

        with override_config(**self.webhook_config):
            with patch.object(
                Profile,
                "can_signup",
                return_value={"success": False},
            ), patch.object(User, "log_event"), patch.object(
                User,
                "email_notification",
            ) as email_notification, patch.object(
                views,
                "send_email_to_admin",
            ) as send_admin:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.post_event(event)

        profile.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(profile.subscription_status, "active")
        email_notification.assert_called_once()
        send_admin.assert_called_once_with(
            "Action Required: Verify returning member",
            template_vars={
                "title": "Action Required: Verify returning member",
                "message": (
                    "An existing member (or someone who clicked 'skip signup I "
                    "just want an account') has setup a membership subscription. "
                    "You must now decide whether to enable their site access."
                ),
            },
            reply_to=profile.user.email,
        )

    def test_payment_failed_notifies_member_after_commit(self):
        profile = self.make_profile()
        event = self.make_event(
            event_type="invoice.payment_failed",
            event_id="evt_payment_failed",
        )

        with override_config(**self.webhook_config):
            with patch.object(User, "log_event"), patch.object(
                User,
                "email_notification",
            ) as email_notification:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.post_event(event)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        email_notification.assert_called_once()
        self.assertEqual(
            email_notification.call_args.args[0],
            "Your membership payment failed",
        )

    def test_subscription_deleted_clears_billing_and_preserves_callback_order(self):
        profile = self.make_profile(state="active", subscription_status="active")
        event = self.make_event(
            event_type="customer.subscription.deleted",
            event_id="evt_subscription_deleted",
            id="sub_test",
            subscription=None,
        )
        order = []
        invoices = SimpleNamespace(
            auto_paging_iter=Mock(return_value=[SimpleNamespace(id="in_open")])
        )

        with override_config(**self.webhook_config):
            with patch.object(
                views.stripe.Invoice,
                "list",
                side_effect=lambda **kwargs: (order.append("list"), invoices)[1],
            ), patch.object(
                views.stripe.Invoice,
                "void_invoice",
                side_effect=lambda invoice_id: order.append("void"),
            ), patch.object(
                views,
                "send_email_to_admin",
                side_effect=lambda *args, **kwargs: order.append("admin"),
            ), patch.object(
                Profile,
                "complete_cancel",
                autospec=True,
                side_effect=lambda self, triggered_by: order.append("cancel"),
            ):
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.post_event(event)

        profile.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(profile.membership_plan)
        self.assertIsNone(profile.stripe_subscription_id)
        self.assertEqual(profile.subscription_status, "inactive")
        self.assertEqual(order, ["list", "void", "admin", "cancel"])

    def test_ignores_unknown_customer_without_claiming_event(self):
        event = self.make_event(event_id="evt_unknown_customer")

        with override_config(**self.webhook_config):
            with patch.object(
                views.Profile.objects,
                "get",
                side_effect=Profile.DoesNotExist,
            ), patch.object(views.StripeWebhook, "_claim_event") as claim, patch.object(
                views.StripeWebhook,
                "_handle_event",
            ) as handle:
                response = self.post_event(event)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        claim.assert_not_called()
        handle.assert_not_called()
        self.assertFalse(
            ProcessedStripeEvent.objects.filter(
                event_id="evt_unknown_customer"
            ).exists()
        )

    def test_reports_duplicate_customer_without_claiming_event(self):
        event = self.make_event(event_id="evt_duplicate_customer")
        error = Profile.MultipleObjectsReturned()

        with override_config(**self.webhook_config):
            with patch.object(
                views.Profile.objects,
                "get",
                side_effect=error,
            ), patch.object(views, "capture_exception") as capture, patch.object(
                views.StripeWebhook,
                "_claim_event",
            ) as claim, patch.object(
                views.StripeWebhook, "_handle_event"
            ) as handle:
                response = self.post_event(event)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        capture.assert_called_once_with(error)
        claim.assert_not_called()
        handle.assert_not_called()
        self.assertFalse(
            ProcessedStripeEvent.objects.filter(
                event_id="evt_duplicate_customer"
            ).exists()
        )

    def test_ignores_unsupported_event_without_claiming_it(self):
        self.make_profile()
        event = self.make_event(
            event_type="customer.updated",
            event_id="evt_unsupported",
        )

        with override_config(**self.webhook_config):
            with patch.object(
                views.StripeWebhook, "_claim_event"
            ) as claim, patch.object(
                views.StripeWebhook,
                "_handle_event",
            ) as handle:
                response = self.post_event(event)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        claim.assert_not_called()
        handle.assert_not_called()
        self.assertFalse(
            ProcessedStripeEvent.objects.filter(event_id="evt_unsupported").exists()
        )

    def test_explicit_null_new_schema_subscription_does_not_fall_back_to_legacy(self):
        self.make_profile()
        event = self.make_event(
            event_id="evt_explicit_null_subscription",
            parent={"subscription_details": {"subscription": None}},
        )

        with override_config(**self.webhook_config):
            with patch.object(views.StripeWebhook, "_handle_event") as handle:
                response = self.post_event(event)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        handle.assert_not_called()
        self.assertFalse(
            ProcessedStripeEvent.objects.filter(
                event_id="evt_explicit_null_subscription"
            ).exists()
        )

    def test_ignores_deleted_subscription_for_a_different_membership(self):
        self.make_profile()
        event = self.make_event(
            event_type="customer.subscription.deleted",
            event_id="evt_other_deleted_subscription",
            id="sub_other",
            subscription=None,
        )

        with override_config(**self.webhook_config):
            with patch.object(views.StripeWebhook, "_handle_event") as handle:
                response = self.post_event(event)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        handle.assert_not_called()
        self.assertFalse(
            ProcessedStripeEvent.objects.filter(
                event_id="evt_other_deleted_subscription"
            ).exists()
        )

    def test_event_without_an_id_is_processed_for_every_delivery(self):
        self.make_profile()
        event = self.make_event()
        event.pop("id")

        with override_config(**self.webhook_config):
            with patch.object(views.StripeWebhook, "_handle_event") as handle:
                first_response = self.post_event(event)
                second_response = self.post_event(event)

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(handle.call_count, 2)
        self.assertEqual(ProcessedStripeEvent.objects.count(), 0)

    def test_non_paid_invoice_does_not_change_membership_or_schedule_callbacks(self):
        profile = self.make_profile()
        event = self.make_event(event_id="evt_not_paid", status="open")

        with override_config(**self.webhook_config):
            with patch.object(Profile, "can_signup") as can_signup, patch.object(
                User,
                "log_event",
            ) as log_event, patch.object(
                User,
                "email_notification",
            ) as email_notification, patch.object(
                views,
                "send_email_to_admin",
            ) as send_admin, patch.object(
                Profile, "complete_signup"
            ) as complete_signup:
                with self.captureOnCommitCallbacks(execute=True) as callbacks:
                    response = self.post_event(event)

        profile.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(profile.subscription_status, "pending")
        self.assertIsNone(profile.subscription_first_created)
        self.assertEqual(callbacks, [])
        can_signup.assert_called_once()
        email_notification.assert_not_called()
        send_admin.assert_not_called()
        complete_signup.assert_not_called()
        log_event.assert_called_once_with("Membership payment received.", "stripe")

    def test_ineligible_noob_member_receives_steps_email_without_admin_notice(self):
        profile = self.make_profile()
        event = self.make_event(event_id="evt_noob_steps")

        with override_config(**self.webhook_config):
            with patch.object(
                Profile,
                "can_signup",
                return_value={"success": False},
            ), patch.object(User, "log_event"), patch.object(
                User,
                "email_notification",
            ) as email_notification, patch.object(
                views,
                "send_email_to_admin",
            ) as send_admin:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.post_event(event)

        profile.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(profile.subscription_status, "active")
        email_notification.assert_called_once()
        send_admin.assert_not_called()

    def test_failed_payment_email_error_is_captured(self):
        self.make_profile()
        event = self.make_event(
            event_type="invoice.payment_failed",
            event_id="evt_failed_payment_email_error",
        )
        error = RuntimeError("email unavailable")

        with override_config(**self.webhook_config):
            with patch.object(User, "log_event"), patch.object(
                User,
                "email_notification",
                side_effect=error,
            ), patch.object(views, "capture_exception") as capture:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.post_event(event)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        capture.assert_called_once_with(error)

    def test_subscription_deleted_reports_invoice_list_failure_and_still_cancels(self):
        profile = self.make_profile(state="active", subscription_status="active")
        event = self.make_event(
            event_type="customer.subscription.deleted",
            event_id="evt_invoice_list_failure",
            id="sub_test",
            subscription=None,
        )
        error = views.stripe.error.APIError("invoice list unavailable")

        with override_config(**self.webhook_config):
            with patch.object(
                views.stripe.Invoice,
                "list",
                side_effect=error,
            ), patch.object(
                views.stripe.Invoice,
                "void_invoice",
            ) as void_invoice, patch.object(
                User, "log_event"
            ) as log_event, patch.object(
                views,
                "send_email_to_admin",
            ) as send_admin, patch.object(
                Profile,
                "complete_cancel",
            ) as complete_cancel, patch.object(
                views,
                "capture_exception",
            ) as capture:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.post_event(event)

        profile.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(profile.subscription_status, "inactive")
        capture.assert_called_once_with(error)
        void_invoice.assert_not_called()
        self.assertEqual(send_admin.call_count, 2)
        self.assertIn(
            "audit cancelled Stripe subscription",
            send_admin.call_args_list[0].kwargs["subject"],
        )
        log_event.assert_called_once()
        complete_cancel.assert_called_once()

    def test_subscription_deleted_continues_after_one_invoice_void_failure(self):
        profile = self.make_profile(state="active", subscription_status="active")
        event = self.make_event(
            event_type="customer.subscription.deleted",
            event_id="evt_invoice_void_failure",
            id="sub_test",
            subscription=None,
        )
        failed_invoice = SimpleNamespace(id="in_failed")
        succeeding_invoice = SimpleNamespace(id="in_succeeds")
        invoices = SimpleNamespace(
            auto_paging_iter=Mock(return_value=[failed_invoice, succeeding_invoice])
        )
        error = views.stripe.error.APIError("invoice void unavailable")

        def void_invoice(invoice_id):
            if invoice_id == failed_invoice.id:
                raise error

        with override_config(**self.webhook_config):
            with patch.object(
                views.stripe.Invoice,
                "list",
                return_value=invoices,
            ), patch.object(
                views.stripe.Invoice,
                "void_invoice",
                side_effect=void_invoice,
            ) as void, patch.object(
                User, "log_event"
            ) as log_event, patch.object(
                views,
                "send_email_to_admin",
            ) as send_admin, patch.object(
                Profile, "complete_cancel"
            ), patch.object(
                views,
                "capture_exception",
            ) as capture:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.post_event(event)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(void.call_args_list[0].args, ("in_failed",))
        self.assertEqual(void.call_args_list[1].args, ("in_succeeds",))
        capture.assert_called_once_with(error)
        log_event.assert_called_once()
        self.assertEqual(send_admin.call_count, 2)
        self.assertIn(
            "void Stripe invoice in_failed",
            send_admin.call_args_list[0].kwargs["subject"],
        )
