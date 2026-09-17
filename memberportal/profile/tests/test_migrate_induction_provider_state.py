import importlib
from datetime import timedelta

from constance.test.unittest import override_config
from django.apps import apps
from django.test import TestCase
from django.utils import timezone

from profile.models import InductionProviderState, Profile, User

induction_migration = importlib.import_module(
    "profile.migrations.0032_induction_provider_external_reference"
)


class InductionProviderStateMigrationTests(TestCase):
    base_config = {
        "CANVAS_INDUCTION_ENABLED": False,
        "MOODLE_INDUCTION_ENABLED": False,
        "ENABLE_DOCUSEAL_INTEGRATION": False,
        "MAX_INDUCTION_DAYS": 180,
    }

    def make_profile(self, last_induction=None, memberdoc_id=None):
        suffix = Profile.objects.count() + 1
        user = User.objects.create_user(
            f"migration-induction-{suffix}@example.test",
            password="test-password",
        )
        return Profile.objects.create(
            user=user,
            first_name="Migration",
            last_name=str(suffix),
            last_induction=last_induction,
            memberdoc_id=memberdoc_id,
        )

    def run_backfill(self):
        induction_migration.backfill_valid_legacy_induction(apps, None)

    def test_backfill_creates_legacy_proof_when_all_providers_are_disabled(self):
        completed_at = timezone.now() - timedelta(days=1)
        profile = self.make_profile(last_induction=completed_at)

        with override_config(**self.base_config):
            self.run_backfill()

        state = InductionProviderState.objects.get(profile=profile, provider="legacy")
        self.assertEqual(state.requirement_key, "legacy:last-induction")
        self.assertEqual(state.status, "complete")
        self.assertEqual(state.completed_at, completed_at)
        self.assertEqual(state.checked_at, completed_at)
        self.assertEqual(state.external_reference, "")
        self.assertFalse(
            InductionProviderState.objects.filter(
                profile=profile, provider__in=["canvas", "moodle", "docuseal"]
            ).exists()
        )

    def test_backfill_creates_legacy_proof_without_docuseal_completion(self):
        completed_at = timezone.now() - timedelta(days=1)
        profile = self.make_profile(last_induction=completed_at, memberdoc_id=712)

        with override_config(
            **{**self.base_config, "ENABLE_DOCUSEAL_INTEGRATION": True}
        ):
            self.run_backfill()

        state = InductionProviderState.objects.get(profile=profile, provider="legacy")
        self.assertEqual(state.status, "complete")
        self.assertEqual(state.completed_at, completed_at)
        self.assertEqual(state.external_reference, "")
        self.assertFalse(
            InductionProviderState.objects.filter(
                profile=profile, provider="docuseal"
            ).exists()
        )

    def test_backfill_keeps_expired_proof_for_runtime_retention_evaluation(self):
        completed_at = timezone.now() - timedelta(days=365)
        profile = self.make_profile(last_induction=completed_at)

        with override_config(**self.base_config):
            self.run_backfill()

        state = InductionProviderState.objects.get(profile=profile, provider="legacy")
        self.assertEqual(state.completed_at, completed_at)
