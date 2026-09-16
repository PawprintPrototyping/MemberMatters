from unittest.mock import Mock, patch

import requests
from constance.test.unittest import override_config
from django.test import TestCase

from profile.models import ListmonkMemberSyncOutbox, Profile, User
from profile import tasks
from services.listmonk import (
    ListmonkConfigurationError,
    ListmonkPermanentError,
    ListmonkTransientError,
)


class ListmonkTaskTests(TestCase):
    config = {
        "ENABLE_LISTMONK_SYNC": True,
        "LISTMONK_URL": "https://listmonk.example.test",
        "LISTMONK_API_USERNAME": "api_user",
        "LISTMONK_API_TOKEN": "token",
        "LISTMONK_ACTIVE_LIST_ID": 10,
        "LISTMONK_INACTIVE_LIST_ID": 20,
        "LISTMONK_REQUEST_TIMEOUT": 5,
    }

    def make_outbox(self, state="active"):
        suffix = ListmonkMemberSyncOutbox.objects.count() + 1
        user = User.objects.create_user(
            f"member-{suffix}@example.test",
            password="test-password",
        )
        profile = Profile.objects.create(
            user=user,
            first_name="Member",
            last_name=str(suffix),
            state=state,
        )
        return ListmonkMemberSyncOutbox.objects.create(
            profile=profile,
            desired_state=state,
        )

    def test_dispatcher_enqueues_pending_rows_only_when_enabled_and_valid(self):
        pending = self.make_outbox()
        complete = self.make_outbox()
        complete.pending = False
        complete.save(update_fields=["pending"])

        with override_config(**self.config):
            with patch("profile.tasks.ListmonkClient.from_config") as from_config:
                with patch("profile.tasks.sync_listmonk_member.delay") as delay:
                    tasks.dispatch_pending_listmonk_sync.run()

        from_config.assert_called_once_with()
        delay.assert_called_once_with(pending.pk)

        with override_config(ENABLE_LISTMONK_SYNC=False):
            with patch("profile.tasks.sync_listmonk_member.delay") as delay:
                tasks.dispatch_pending_listmonk_sync.run()
        delay.assert_not_called()

    def test_dispatcher_skips_when_configuration_is_invalid(self):
        self.make_outbox()
        with override_config(**self.config):
            with patch(
                "profile.tasks.ListmonkClient.from_config",
                side_effect=ListmonkConfigurationError("invalid"),
            ):
                with patch("profile.tasks.sync_listmonk_member.delay") as delay:
                    tasks.dispatch_pending_listmonk_sync.run()
        delay.assert_not_called()

    def test_worker_records_success_and_remote_subscriber_id(self):
        outbox = self.make_outbox()
        client = Mock()
        client.synchronize_member.return_value = 321

        with override_config(**self.config):
            with patch("profile.tasks.ListmonkClient.from_config", return_value=client):
                tasks.sync_listmonk_member.run(outbox.pk)

        outbox.refresh_from_db()
        self.assertFalse(outbox.pending)
        self.assertEqual(outbox.remote_subscriber_id, 321)
        self.assertIsNotNone(outbox.synced_at)
        self.assertEqual(outbox.last_error, "")
        client.synchronize_member.assert_called_once_with(
            remote_subscriber_id=None,
            user_id=outbox.profile.user_id,
            profile_id=outbox.profile_id,
            email=outbox.profile.user.email,
            name=outbox.profile.get_full_name(),
            desired_state="active",
        )

    def test_worker_retries_transient_failures_and_records_failure(self):
        outbox = self.make_outbox()
        client = Mock()
        client.synchronize_member.side_effect = ListmonkTransientError("unavailable")
        retry_error = RuntimeError("retry scheduled")

        with override_config(**self.config):
            with patch("profile.tasks.ListmonkClient.from_config", return_value=client):
                with patch.object(
                    tasks.sync_listmonk_member,
                    "retry",
                    side_effect=retry_error,
                ) as retry:
                    with self.assertRaises(RuntimeError):
                        tasks.sync_listmonk_member.run(outbox.pk)

        outbox.refresh_from_db()
        self.assertTrue(outbox.pending)
        self.assertEqual(outbox.attempt_count, 1)
        self.assertEqual(outbox.last_error, "unavailable")
        retry.assert_called_once_with(
            exc=client.synchronize_member.side_effect,
            countdown=60,
        )

    def test_worker_records_permanent_error_without_retry(self):
        outbox = self.make_outbox()
        client = Mock()
        client.synchronize_member.side_effect = ListmonkPermanentError("rejected")

        with override_config(**self.config):
            with patch("profile.tasks.ListmonkClient.from_config", return_value=client):
                with patch("profile.tasks.capture_exception") as capture_exception:
                    with patch.object(tasks.sync_listmonk_member, "retry") as retry:
                        tasks.sync_listmonk_member.run(outbox.pk)

        outbox.refresh_from_db()
        self.assertTrue(outbox.pending)
        self.assertEqual(outbox.attempt_count, 1)
        self.assertEqual(outbox.last_error, "rejected")
        capture_exception.assert_called_once_with(client.synchronize_member.side_effect)
        retry.assert_not_called()

    def test_stale_failure_does_not_modify_newer_outbox_revision(self):
        outbox = self.make_outbox()
        outbox.revision = 2
        outbox.last_error = "newer error"
        outbox.save(update_fields=["revision", "last_error"])

        tasks._record_failure(outbox.pk, 1, requests.ConnectionError("old error"))

        outbox.refresh_from_db()
        self.assertEqual(outbox.attempt_count, 0)
        self.assertEqual(outbox.last_error, "newer error")
