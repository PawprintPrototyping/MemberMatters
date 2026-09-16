import importlib
import json

from constance.backends.database.models import Constance
from django.apps import apps
from django.test import TestCase

email_migration = importlib.import_module(
    "profile.migrations.0029_migrate_email_backend_configuration"
)


class EmailBackendConfigurationMigrationTests(TestCase):
    def setUp(self):
        super().setUp()
        Constance.objects.filter(
            key__in=(
                *email_migration.LEGACY_EMAIL_KEYS,
                *email_migration.TARGET_EMAIL_KEYS,
            )
        ).delete()

    def tearDown(self):
        Constance.objects.filter(
            key__in=(
                *email_migration.LEGACY_EMAIL_KEYS,
                *email_migration.TARGET_EMAIL_KEYS,
            )
        ).delete()
        super().tearDown()

    def seed(self, **values):
        Constance.objects.bulk_create(
            [Constance(key=key, value=value) for key, value in values.items()]
        )

    def run_migration(self):
        email_migration.migrate_email_backend_configuration(apps, None)

    def target_values(self):
        return {
            setting.key: setting.value
            for setting in Constance.objects.filter(
                key__in=email_migration.TARGET_EMAIL_KEYS
            )
        }

    def assert_legacy_values_removed(self):
        self.assertFalse(
            Constance.objects.filter(key__in=email_migration.LEGACY_EMAIL_KEYS).exists()
        )

    def test_postmark_precedes_smtp_and_preserves_both_profiles(self):
        self.seed(
            POSTMARK_API_KEY="postmark-token",
            SMTP_HOSTNAME="smtp.example.test",
            SMTP_PORT=2525,
            SMTP_USE_TLS=False,
            SMTP_USERNAME="mailer",
            SMTP_PASSWORD="smtp-password",
        )

        self.run_migration()

        values = self.target_values()
        self.assertTrue(values["EMAIL_ENABLED"])
        self.assertEqual(values["EMAIL_BACKEND"], "postmark")
        self.assertEqual(
            json.loads(values["EMAIL_BACKEND_OPTIONS"]),
            {
                "postmark": {"server_token": "postmark-token"},
                "smtp": {
                    "host": "smtp.example.test",
                    "port": 2525,
                    "username": "mailer",
                    "password": "smtp-password",
                    "use_tls": False,
                    "use_ssl": False,
                    "timeout": 10,
                },
            },
        )
        self.assert_legacy_values_removed()

    def test_smtp_only_configuration_is_migrated(self):
        self.seed(
            SMTP_HOSTNAME="smtp.example.test",
            SMTP_PORT="not-a-port",
            SMTP_USE_TLS="yes",
            SMTP_USERNAME="mailer",
            SMTP_PASSWORD="smtp-password",
        )

        self.run_migration()

        values = self.target_values()
        self.assertTrue(values["EMAIL_ENABLED"])
        self.assertEqual(values["EMAIL_BACKEND"], "smtp")
        self.assertEqual(
            json.loads(values["EMAIL_BACKEND_OPTIONS"]),
            {
                "smtp": {
                    "host": "smtp.example.test",
                    "port": 587,
                    "username": "mailer",
                    "password": "smtp-password",
                    "use_tls": True,
                    "use_ssl": False,
                    "timeout": 10,
                }
            },
        )
        self.assert_legacy_values_removed()

    def test_placeholder_postmark_key_creates_disabled_configuration(self):
        self.seed(POSTMARK_API_KEY="PLEASE_CHANGE_ME")

        self.run_migration()

        self.assertEqual(
            self.target_values(),
            {
                "EMAIL_BACKEND_OPTIONS": "{}",
                "EMAIL_BACKEND": "disabled",
                "EMAIL_ENABLED": False,
            },
        )
        self.assert_legacy_values_removed()

    def test_partial_target_configuration_is_replaced_by_usable_legacy_profile(self):
        self.seed(
            EMAIL_ENABLED=False,
            POSTMARK_API_KEY="postmark-token",
        )

        self.run_migration()

        self.assertEqual(
            self.target_values(),
            {
                "EMAIL_BACKEND_OPTIONS": json.dumps(
                    {"postmark": {"server_token": "postmark-token"}}
                ),
                "EMAIL_BACKEND": "postmark",
                "EMAIL_ENABLED": True,
            },
        )
        self.assert_legacy_values_removed()

    def test_partial_target_without_legacy_profile_is_retained(self):
        self.seed(
            EMAIL_ENABLED=False,
            POSTMARK_API_KEY="PLEASE_CHANGE_ME",
        )

        self.run_migration()

        self.assertEqual(self.target_values(), {"EMAIL_ENABLED": False})
        self.assert_legacy_values_removed()

    def test_complete_target_configuration_is_retained(self):
        configured_options = '{"smtp": {"host": "configured.example.test"}}'
        self.seed(
            EMAIL_BACKEND_OPTIONS=configured_options,
            EMAIL_BACKEND="smtp",
            EMAIL_ENABLED=True,
            POSTMARK_API_KEY="postmark-token",
        )

        self.run_migration()

        self.assertEqual(
            self.target_values(),
            {
                "EMAIL_BACKEND_OPTIONS": configured_options,
                "EMAIL_BACKEND": "smtp",
                "EMAIL_ENABLED": True,
            },
        )
        self.assert_legacy_values_removed()
