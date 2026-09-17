import logging
from datetime import timedelta

import requests
from constance import config
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from membermatters.celeryapp import app
from sentry_sdk import capture_exception

from profile.models import ListmonkMemberSyncOutbox
from services.listmonk import (
    ListmonkClient,
    ListmonkConfigurationError,
    ListmonkPermanentError,
    ListmonkTransientError,
)

logger = logging.getLogger("profile:listmonk")
PENDING_DISPATCH_INTERVAL = timedelta(minutes=5)
PENDING_DISPATCH_LIMIT = 100


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        PENDING_DISPATCH_INTERVAL,
        dispatch_pending_listmonk_sync.s(),
        name="dispatch_pending_listmonk_sync",
    )


@app.task
def dispatch_pending_listmonk_sync():
    if not config.ENABLE_LISTMONK_SYNC:
        return

    try:
        ListmonkClient.from_config()
    except ListmonkConfigurationError as error:
        logger.error("Listmonk synchronization is not configured: %s", error)
        return

    outbox_ids = list(
        ListmonkMemberSyncOutbox.objects.filter(pending=True)
        .order_by("updated_at")
        .values_list("pk", flat=True)[:PENDING_DISPATCH_LIMIT]
    )
    for outbox_id in outbox_ids:
        try:
            sync_listmonk_member.delay(outbox_id)
        except Exception as error:
            logger.exception("Unable to dispatch Listmonk outbox %s", outbox_id)
            capture_exception(error)


@app.task(bind=True, max_retries=5)
def sync_listmonk_member(self, outbox_id):
    if not config.ENABLE_LISTMONK_SYNC:
        return

    revision = None
    profile_id = None
    try:
        # The lock intentionally covers the remote call. It serializes tasks
        # for a member so an older active/inactive transition cannot finish
        # after a newer one and revert Listmonk membership remotely.
        with transaction.atomic():
            outbox = (
                ListmonkMemberSyncOutbox.objects.select_for_update()
                .select_related("profile__user")
                .get(pk=outbox_id)
            )
            if not outbox.pending:
                return

            revision = outbox.revision
            profile = outbox.profile
            profile_id = profile.pk
            client = ListmonkClient.from_config()
            remote_subscriber_id = client.synchronize_member(
                remote_subscriber_id=outbox.remote_subscriber_id,
                user_id=profile.user_id,
                profile_id=profile.pk,
                email=profile.user.email,
                name=profile.get_display_name(),
                desired_state=outbox.desired_state,
            )
            outbox.remote_subscriber_id = remote_subscriber_id
            outbox.pending = False
            outbox.synced_at = timezone.now()
            outbox.last_error = ""
            outbox.last_attempt_at = timezone.now()
            outbox.save(
                update_fields=[
                    "remote_subscriber_id",
                    "pending",
                    "synced_at",
                    "last_error",
                    "last_attempt_at",
                    "updated_at",
                ]
            )
    except ListmonkMemberSyncOutbox.DoesNotExist:
        return
    except (requests.RequestException, ListmonkTransientError) as error:
        _record_failure(outbox_id, revision, error)
        countdown = min(60 * (2**self.request.retries), 3600)
        raise self.retry(exc=error, countdown=countdown)
    except (ListmonkConfigurationError, ListmonkPermanentError) as error:
        _record_failure(outbox_id, revision, error)
        logger.error("Listmonk sync failed for profile %s: %s", profile_id, error)
        capture_exception(error)
    except Exception as error:
        _record_failure(outbox_id, revision, error)
        logger.exception("Unexpected Listmonk sync failure for profile %s", profile_id)
        capture_exception(error)
        raise self.retry(exc=error, countdown=60)


def _record_failure(outbox_id, revision, error):
    if revision is None:
        return

    ListmonkMemberSyncOutbox.objects.filter(
        pk=outbox_id,
        revision=revision,
    ).update(
        attempt_count=F("attempt_count") + 1,
        last_attempt_at=timezone.now(),
        last_error=str(error)[:1000],
        updated_at=timezone.now(),
    )
