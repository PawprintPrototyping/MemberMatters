from django.db import models


class ProcessedStripeEvent(models.Model):
    """Idempotency record for Stripe webhook events.

    Stripe retries webhook deliveries on non-2xx responses or timeouts for up
    to ~3 days. We store every successfully-validated event id here and
    skip duplicates so retries don't re-run side effects (emails, SMS, state
    changes). Cleaned up periodically by an admin/cron task."""

    event_id = models.CharField(max_length=255, primary_key=True)
    event_type = models.CharField(max_length=100)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Processed Stripe Event"
        verbose_name_plural = "Processed Stripe Events"


class PaymentPlanSwitchOperation(models.Model):
    """Durable state for a Stripe subscription Price replacement.

    The row is created before the Stripe mutation. If the request dies after
    Stripe succeeds but before Profile is saved, the periodic reconciliation
    task can inspect Stripe and finish the local update using this record.
    """

    STATUS_PENDING = "pending"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_FAILED, "Failed"),
    )

    profile = models.OneToOneField(
        "profile.Profile",
        on_delete=models.CASCADE,
        related_name="payment_plan_switch_operation",
    )
    current_plan = models.ForeignKey(
        "api_admin_tools.PaymentPlan",
        on_delete=models.PROTECT,
        related_name="switch_operations_from",
    )
    target_plan = models.ForeignKey(
        "api_admin_tools.PaymentPlan",
        on_delete=models.PROTECT,
        related_name="switch_operations_to",
    )
    stripe_subscription_id = models.CharField(max_length=100)
    idempotency_key = models.CharField(max_length=255, unique=True)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["status", "updated_at"])]
