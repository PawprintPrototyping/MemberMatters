from io import StringIO
from unittest.mock import patch

from constance.test.unittest import override_config
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.test import TestCase

from profile.models import (
    ListmonkMemberSyncOutbox,
    Profile,
    User,
    queue_listmonk_member_sync,
)


class ListmonkOutboxTests(TestCase):
    enabled_config = {"ENABLE_LISTMONK_SYNC": True}

    def make_profile(self, state="noob"):
        suffix = Profile.objects.count() + 1
        user = User.objects.create_user(
            f"member-{suffix}@example.test",
            password="test-password",
        )
        return Profile.objects.create(
            user=user,
            first_name="Member",
            last_name=str(suffix),
            state=state,
        )

    def test_queue_creates_outbox_and_defers_dispatch_until_commit(self):
        profile = self.make_profile()

        with override_config(**self.enabled_config):
            with patch("profile.tasks.sync_listmonk_member.delay") as delay:
                with self.captureOnCommitCallbacks(execute=True):
                    outbox = queue_listmonk_member_sync(profile, "active")

        self.assertEqual(outbox.desired_state, "active")
        self.assertTrue(outbox.pending)
        self.assertEqual(outbox.revision, 1)
        delay.assert_called_once_with(outbox.pk)

    def test_requeue_coalesces_latest_state_and_preserves_remote_subscriber(self):
        profile = self.make_profile()
        outbox = ListmonkMemberSyncOutbox.objects.create(
            profile=profile,
            desired_state="active",
            pending=False,
            remote_subscriber_id=123,
            attempt_count=4,
            last_error="previous failure",
        )

        with override_config(ENABLE_LISTMONK_SYNC=False):
            queue_listmonk_member_sync(profile, "inactive")

        outbox.refresh_from_db()
        self.assertEqual(outbox.desired_state, "inactive")
        self.assertEqual(outbox.revision, 2)
        self.assertTrue(outbox.pending)
        self.assertEqual(outbox.remote_subscriber_id, 123)
        self.assertEqual(outbox.attempt_count, 0)
        self.assertEqual(outbox.last_error, "")
        self.assertIsNone(outbox.synced_at)

    def test_queue_rejects_unsupported_member_state(self):
        with self.assertRaisesMessage(ValueError, "Unsupported Listmonk member state"):
            queue_listmonk_member_sync(self.make_profile(), "noob")

    def test_disabled_sync_persists_outbox_without_dispatching_task(self):
        profile = self.make_profile()

        with override_config(ENABLE_LISTMONK_SYNC=False):
            with patch("profile.tasks.sync_listmonk_member.delay") as delay:
                with self.captureOnCommitCallbacks(execute=True):
                    queue_listmonk_member_sync(profile, "active")

        delay.assert_not_called()
        self.assertTrue(
            ListmonkMemberSyncOutbox.objects.filter(profile=profile).exists()
        )

    def test_rolled_back_state_change_discards_outbox_and_dispatch(self):
        profile = self.make_profile()

        with override_config(**self.enabled_config):
            with patch("profile.tasks.sync_listmonk_member.delay") as delay:
                with self.assertRaises(RuntimeError):
                    with transaction.atomic():
                        queue_listmonk_member_sync(profile, "active")
                        raise RuntimeError("rollback")
                with self.captureOnCommitCallbacks(execute=True):
                    pass

        self.assertFalse(
            ListmonkMemberSyncOutbox.objects.filter(profile=profile).exists()
        )
        delay.assert_not_called()

    def test_activate_and_deactivate_queue_only_real_state_transitions(self):
        activating = self.make_profile(state="noob")
        deactivating = self.make_profile(state="active")

        with patch("profile.models.queue_listmonk_member_sync") as queue:
            with patch.object(activating, "sync_access"):
                with patch.object(activating.user, "email_membership_application"):
                    with patch.object(activating.user, "email_welcome"):
                        self.assertTrue(activating.activate())
            with patch.object(deactivating, "sync_access"):
                with patch.object(deactivating.user, "email_disable_member_access"):
                    with patch("profile.models.sms.SMS"):
                        self.assertTrue(deactivating.deactivate())

            self.assertFalse(activating.activate())
            self.assertFalse(deactivating.deactivate())

        self.assertEqual(queue.call_args_list[0].args, (activating, "active"))
        self.assertEqual(queue.call_args_list[1].args, (deactivating, "inactive"))
        self.assertEqual(queue.call_count, 2)


class QueueListmonkSyncCommandTests(TestCase):
    def make_profile(self, state):
        suffix = Profile.objects.count() + 1
        user = User.objects.create_user(
            f"member-{suffix}@example.test",
            password="test-password",
        )
        return Profile.objects.create(
            user=user,
            first_name="Member",
            last_name=str(suffix),
            state=state,
        )

    def test_dry_run_reports_eligible_members_without_creating_outbox_rows(self):
        self.make_profile("active")
        self.make_profile("inactive")
        self.make_profile("noob")
        output = StringIO()

        call_command("queue_listmonk_sync", "--dry-run", stdout=output)

        self.assertIn("would queue=2", output.getvalue())
        self.assertEqual(ListmonkMemberSyncOutbox.objects.count(), 0)

    def test_command_queues_selected_state_and_rejects_negative_limit(self):
        active = self.make_profile("active")
        self.make_profile("inactive")
        output = StringIO()

        with override_config(ENABLE_LISTMONK_SYNC=False):
            call_command("queue_listmonk_sync", "--state", "active", stdout=output)

        self.assertIn("queued=1", output.getvalue())
        self.assertEqual(
            ListmonkMemberSyncOutbox.objects.get().profile_id,
            active.pk,
        )
        with self.assertRaisesMessage(CommandError, "--limit must be zero or greater"):
            call_command("queue_listmonk_sync", "--limit", "-1")
