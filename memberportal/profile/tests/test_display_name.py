from constance.test.unittest import override_config
from django.test import TestCase

from profile.models import Profile


class DisplayNameTests(TestCase):
    def make_profile(self, screen_name=None):
        return Profile(
            first_name="First",
            last_name="Last",
            screen_name=screen_name,
        )

    def test_uses_full_name_by_default(self):
        profile = self.make_profile(screen_name="public-handle")

        with override_config(PREFER_SCREEN_NAME_OVER_FULL_NAME=False):
            self.assertEqual(profile.get_display_name(), "First Last")

    def test_prefers_screen_name_when_enabled(self):
        profile = self.make_profile(screen_name="public-handle")

        with override_config(PREFER_SCREEN_NAME_OVER_FULL_NAME=True):
            self.assertEqual(profile.get_display_name(), "public-handle")

    def test_enabled_preference_falls_back_when_screen_name_is_unset(self):
        with override_config(PREFER_SCREEN_NAME_OVER_FULL_NAME=True):
            for screen_name in (None, "", "   "):
                with self.subTest(screen_name=screen_name):
                    profile = self.make_profile(screen_name=screen_name)
                    self.assertEqual(profile.get_display_name(), "First Last")

    def test_include_screen_name_preserves_legacy_format_when_preference_disabled(self):
        profile = self.make_profile(screen_name="public-handle")

        with override_config(PREFER_SCREEN_NAME_OVER_FULL_NAME=False):
            self.assertEqual(
                profile.get_display_name(include_screen_name=True),
                "First Last (public-handle)",
            )

    def test_include_screen_name_does_not_duplicate_preferred_screen_name(self):
        profile = self.make_profile(screen_name="public-handle")

        with override_config(PREFER_SCREEN_NAME_OVER_FULL_NAME=True):
            self.assertEqual(
                profile.get_display_name(include_screen_name=True),
                "public-handle",
            )
