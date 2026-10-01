from datetime import timedelta
from unittest.mock import call, patch

from django.test import TestCase
from django.utils import timezone

from api_admin_tools.models import MemberTier, PaymentPlan
from api_billing.models import PaymentPlanSwitchOperation, ProcessedStripeEvent
from api_billing.tasks import (
    EVENT_RETENTION_DAYS,
    cleanup_processed_stripe_events,
    reconcile_pending_payment_plan_switches,
)
from profile.models import Profile, User


class BillingTaskTests(TestCase):
    def make_profile_and_plans(self):
        suffix = Profile.objects.count() + 1
        user = User.objects.create_user(
            f"billing-task-{suffix}@example.test",
            password="test-password",
        )
        profile = Profile.objects.create(
            user=user,
            first_name="Billing",
            last_name="Task",
            state="active",
            stripe_subscription_id=f"sub_billing_task_{suffix}",
            subscription_status="active",
        )
        tier = MemberTier.objects.create(
            name=f"Billing Task Tier {suffix}",
            description=f"Billing task tier {suffix}",
            stripe_id=f"prod_billing_task_{suffix}",
        )
        current_plan = PaymentPlan.objects.create(
            name=f"Billing Task Current {suffix}",
            description=f"Billing task current {suffix}",
            stripe_id=f"price_billing_task_current_{suffix}",
            member_tier=tier,
            currency="aud",
            cost=2000,
            interval_count=1,
            interval="month",
        )
        target_plan = PaymentPlan.objects.create(
            name=f"Billing Task Target {suffix}",
            description=f"Billing task target {suffix}",
            stripe_id=f"price_billing_task_target_{suffix}",
            member_tier=tier,
            currency="aud",
            cost=3000,
            interval_count=1,
            interval="month",
        )
        return profile, current_plan, target_plan

    def test_cleanup_removes_only_expired_processed_events(self):
        now = timezone.now()
        expired = ProcessedStripeEvent.objects.create(
            event_id="evt_expired",
            event_type="invoice.paid",
        )
        recent = ProcessedStripeEvent.objects.create(
            event_id="evt_recent",
            event_type="invoice.paid",
        )
        ProcessedStripeEvent.objects.filter(pk=expired.pk).update(
            processed_at=now - timedelta(days=EVENT_RETENTION_DAYS + 1)
        )
        ProcessedStripeEvent.objects.filter(pk=recent.pk).update(
            processed_at=now - timedelta(days=EVENT_RETENTION_DAYS - 1)
        )

        with patch("api_billing.tasks.timezone.now", return_value=now):
            cleanup_processed_stripe_events()

        self.assertFalse(ProcessedStripeEvent.objects.filter(pk=expired.pk).exists())
        self.assertTrue(ProcessedStripeEvent.objects.filter(pk=recent.pk).exists())

    @patch("api_billing.tasks.process_payment_plan_switch")
    def test_reconciliation_processes_pending_operations_only(self, process):
        profile, current_plan, target_plan = self.make_profile_and_plans()
        pending = PaymentPlanSwitchOperation.objects.create(
            profile=profile,
            current_plan=current_plan,
            target_plan=target_plan,
            stripe_subscription_id=profile.stripe_subscription_id,
            idempotency_key="plan-switch-pending-task-test",
            status=PaymentPlanSwitchOperation.STATUS_PENDING,
        )

        failed_profile, failed_current, failed_target = self.make_profile_and_plans()
        failed = PaymentPlanSwitchOperation.objects.create(
            profile=failed_profile,
            current_plan=failed_current,
            target_plan=failed_target,
            stripe_subscription_id=failed_profile.stripe_subscription_id,
            idempotency_key="plan-switch-failed-task-test",
            status=PaymentPlanSwitchOperation.STATUS_FAILED,
        )

        reconcile_pending_payment_plan_switches()

        process.assert_called_once_with(pending.pk)
        self.assertNotIn(call(failed.pk), process.call_args_list)
