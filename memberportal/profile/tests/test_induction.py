from datetime import timedelta
from unittest.mock import patch

from constance.test.unittest import override_config
from django.test import TestCase
from django.utils import timezone

from profile.models import InductionProviderState, Profile, User
from services import induction


class ProviderAwareInductionTests(TestCase):
    base_config = {
        "ENABLE_STRIPE_MEMBERSHIP_PAYMENTS": False,
        "TERMS_ACCEPTANCE_CARDS": "[]",
        "REQUIRE_ACCESS_CARD": False,
        "CANVAS_INDUCTION_ENABLED": False,
        "CANVAS_INDUCTION_COURSE_ID": "canvas-1",
        "MOODLE_INDUCTION_ENABLED": False,
        "MOODLE_INDUCTION_COURSE_ID": "moodle-1",
        "ENABLE_DOCUSEAL_INTEGRATION": False,
        "DOCUSEAL_TEMPLATE_ID": 1,
        "MIN_INDUCTION_SCORE": 99,
        "MAX_INDUCTION_DAYS": 180,
    }

    def make_profile(self):
        suffix = Profile.objects.count() + 1
        user = User.objects.create_user(
            f"induction-{suffix}@example.test",
            password="test-password",
        )
        return Profile.objects.create(
            user=user,
            first_name="Induction",
            last_name=str(suffix),
        )

    def make_state(
        self,
        profile,
        requirement,
        status="complete",
        completed_at=None,
        **kwargs,
    ):
        return InductionProviderState.objects.create(
            profile=profile,
            provider=requirement.provider,
            requirement_key=requirement.requirement_key,
            status=status,
            completed_at=completed_at or timezone.now(),
            checked_at=timezone.now(),
            **kwargs,
        )

    def test_zero_max_induction_days_accepts_old_complete_state(self):
        profile = self.make_profile()
        config = {
            **self.base_config,
            "CANVAS_INDUCTION_ENABLED": True,
            "MAX_INDUCTION_DAYS": 0,
        }

        with override_config(**config):
            requirement = induction.enabled_requirements()[0]
            completed_at = timezone.now() - timedelta(days=3650)
            self.make_state(profile, requirement, completed_at=completed_at)

            status = induction.get_status(profile)
            self.assertTrue(status["complete"])
            self.assertEqual(status["providers"][0]["status"], "complete")
            self.assertEqual(status["providers"][0]["completedAt"], completed_at)
            self.assertTrue(profile.can_signup()["success"])

    def test_legacy_proof_supports_later_lms_enablement_with_old_precedence(self):
        profile = self.make_profile()
        completed_at = timezone.now() - timedelta(days=1)
        InductionProviderState.objects.create(
            profile=profile,
            provider="legacy",
            requirement_key="legacy:last-induction",
            status="complete",
            completed_at=completed_at,
            checked_at=completed_at,
        )
        config = {
            **self.base_config,
            "CANVAS_INDUCTION_ENABLED": True,
            "MOODLE_INDUCTION_ENABLED": True,
        }

        with override_config(**config):
            status = induction.get_status(profile)
            providers = {item["provider"]: item for item in status["providers"]}
            self.assertTrue(providers["moodle"]["complete"])
            self.assertFalse(providers["canvas"]["complete"])
            self.assertFalse(status["complete"])

        with override_config(**{**config, "CANVAS_INDUCTION_ENABLED": False}):
            self.assertTrue(profile.can_signup()["success"])

        with override_config(**{**config, "MOODLE_INDUCTION_ENABLED": False}):
            self.assertTrue(profile.can_signup()["success"])

    def test_docuseal_never_uses_legacy_proof(self):
        profile = self.make_profile()
        completed_at = timezone.now() - timedelta(days=1)
        InductionProviderState.objects.create(
            profile=profile,
            provider="legacy",
            requirement_key="legacy:last-induction",
            status="complete",
            completed_at=completed_at,
            checked_at=completed_at,
        )

        with override_config(
            **{**self.base_config, "ENABLE_DOCUSEAL_INTEGRATION": True}
        ):
            status = induction.get_status(profile)
            self.assertFalse(status["complete"])
            self.assertEqual(status["providers"][0]["provider"], "docuseal")
            self.assertFalse(status["providers"][0]["complete"])

    def test_each_enabled_provider_is_an_independent_signup_gate(self):
        profile = self.make_profile()
        config = {
            **self.base_config,
            "CANVAS_INDUCTION_ENABLED": True,
            "MOODLE_INDUCTION_ENABLED": True,
        }

        with override_config(**config):
            requirements = {
                requirement.provider: requirement
                for requirement in induction.enabled_requirements()
            }
            self.make_state(profile, requirements["moodle"])
            self.make_state(profile, requirements["canvas"], status="pending")

            self.assertFalse(induction.get_status(profile)["complete"])
            self.assertIn("induction", profile.can_signup()["requiredSteps"])

            with override_config(**{**config, "CANVAS_INDUCTION_ENABLED": False}):
                self.assertTrue(profile.can_signup()["success"])

        second_profile = self.make_profile()
        with override_config(**config):
            requirements = {
                requirement.provider: requirement
                for requirement in induction.enabled_requirements()
            }
            self.make_state(second_profile, requirements["canvas"])
            self.make_state(second_profile, requirements["moodle"], status="pending")

            with override_config(**{**config, "MOODLE_INDUCTION_ENABLED": False}):
                self.assertTrue(second_profile.can_signup()["success"])

    def test_docuseal_reservation_creates_once_and_reissues_on_template_change(self):
        profile = self.make_profile()
        config = {
            **self.base_config,
            "ENABLE_DOCUSEAL_INTEGRATION": True,
            "DOCUSEAL_TEMPLATE_ID": 101,
        }
        issued_ids = iter((501, 502))

        def create_submission(target):
            submission_id = next(issued_ids)
            target.memberdoc_id = submission_id
            target.memberdoc_url = f"https://docs.example/{submission_id}"
            target.save(update_fields=["memberdoc_id", "memberdoc_url"])

        with override_config(**config):
            requirement_101 = induction.enabled_requirements()[0]
            with patch(
                "services.induction.create_submission_for_subscription",
                side_effect=create_submission,
            ) as create:
                _, first = induction._reserve_docuseal_submission(
                    profile.pk, requirement_101
                )
                _, repeated = induction._reserve_docuseal_submission(
                    profile.pk, requirement_101
                )
                self.assertEqual(create.call_count, 1)
                self.assertEqual(first.external_reference, "501")
                self.assertEqual(repeated.external_reference, "501")

                with override_config(**{**config, "DOCUSEAL_TEMPLATE_ID": 202}):
                    requirement_202 = induction.enabled_requirements()[0]
                    _, reissued = induction._reserve_docuseal_submission(
                        profile.pk, requirement_202
                    )
                    _, repeated_reissue = induction._reserve_docuseal_submission(
                        profile.pk, requirement_202
                    )

                self.assertEqual(create.call_count, 2)
                self.assertEqual(reissued.external_reference, "502")
                self.assertEqual(repeated_reissue.external_reference, "502")

            self.assertEqual(
                InductionProviderState.objects.filter(
                    profile=profile, provider="docuseal"
                ).count(),
                2,
            )

    def test_status_and_can_signup_do_not_verify_external_providers(self):
        profile = self.make_profile()
        config = {
            **self.base_config,
            "CANVAS_INDUCTION_ENABLED": True,
            "MOODLE_INDUCTION_ENABLED": True,
            "ENABLE_DOCUSEAL_INTEGRATION": True,
        }

        with override_config(**config):
            for requirement in induction.enabled_requirements():
                self.make_state(profile, requirement)

            with patch("services.induction.Canvas") as canvas, patch(
                "services.induction.moodle_get_user_from_email"
            ) as moodle_user, patch(
                "services.induction.moodle_get_course_activity_completion_status"
            ) as moodle_completion, patch(
                "services.induction.create_submission_for_subscription"
            ) as create_docuseal, patch(
                "services.induction.get_docuseal_submission"
            ) as get_docuseal:
                self.assertTrue(induction.get_status(profile)["complete"])
                self.assertTrue(profile.can_signup()["success"])

            canvas.assert_not_called()
            moodle_user.assert_not_called()
            moodle_completion.assert_not_called()
            create_docuseal.assert_not_called()
            get_docuseal.assert_not_called()
