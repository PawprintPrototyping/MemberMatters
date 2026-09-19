from datetime import timedelta
from django.utils import timezone
from membermatters.celeryapp import app
from api_billing.models import (
    PaymentPlanSwitchOperation,
    ProcessedStripeEvent,
)
from api_billing.plan_switch import process_payment_plan_switch
import logging

logger = logging.getLogger("celery:api_billing")

# Stripe retries webhooks for ~72h; 30 days is a safe retention for
# forensic lookups. Tune if the table grows unexpectedly.
EVENT_RETENTION_DAYS = 30


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        timedelta(days=1),
        cleanup_processed_stripe_events.s(),
        name="cleanup_processed_stripe_events",
    )
    sender.add_periodic_task(
        timedelta(minutes=5),
        reconcile_pending_payment_plan_switches.s(),
        name="reconcile_pending_payment_plan_switches",
    )


@app.task
def cleanup_processed_stripe_events():
    cutoff = timezone.now() - timedelta(days=EVENT_RETENTION_DAYS)
    deleted, _ = ProcessedStripeEvent.objects.filter(processed_at__lt=cutoff).delete()
    logger.info(f"Deleted {deleted} expired Stripe webhook dedup rows")


@app.task
def reconcile_pending_payment_plan_switches():
    operation_ids = PaymentPlanSwitchOperation.objects.filter(
        status=PaymentPlanSwitchOperation.STATUS_PENDING
    ).values_list("pk", flat=True)
    for operation_id in operation_ids:
        process_payment_plan_switch(operation_id)
