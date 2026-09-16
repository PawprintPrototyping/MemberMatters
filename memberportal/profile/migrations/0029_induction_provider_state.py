from datetime import timedelta

from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


def backfill_valid_legacy_induction(apps, schema_editor):
    """Preserve completion proven by the former aggregate induction field."""
    from constance import config

    Profile = apps.get_model("profile", "Profile")
    InductionProviderState = apps.get_model("profile", "InductionProviderState")
    now = timezone.now()

    providers = []
    # Match the old provider-selection behavior: Moodle overrode Canvas, and
    # DocuSeal was an additional requirement when enabled.
    if config.MOODLE_INDUCTION_ENABLED:
        providers.append(
            (
                "moodle",
                f"moodle:course:{config.MOODLE_INDUCTION_COURSE_ID}:"
                f"minimum-score:{config.MIN_INDUCTION_SCORE}",
            )
        )
    elif config.CANVAS_INDUCTION_ENABLED:
        providers.append(
            (
                "canvas",
                f"canvas:course:{config.CANVAS_INDUCTION_COURSE_ID}:"
                f"minimum-score:{config.MIN_INDUCTION_SCORE}",
            )
        )
    if config.ENABLE_DOCUSEAL_INTEGRATION:
        providers.append(
            ("docuseal", f"docuseal:template:{config.DOCUSEAL_TEMPLATE_ID}")
        )

    for profile in Profile.objects.exclude(last_induction__isnull=True):
        if config.MAX_INDUCTION_DAYS > 0 and profile.last_induction < now - timedelta(
            days=config.MAX_INDUCTION_DAYS
        ):
            continue
        for provider, requirement_key in providers:
            # `last_induction` can prove the legacy LMS path, but it never
            # proves that a DocuSeal agreement was signed. Preserve an
            # existing DocuSeal submission reference as pending so refresh()
            # verifies it; otherwise it will issue a new agreement.
            is_docuseal = provider == "docuseal"
            InductionProviderState.objects.get_or_create(
                profile_id=profile.pk,
                provider=provider,
                requirement_key=requirement_key,
                defaults={
                    "status": "pending" if is_docuseal else "complete",
                    "completed_at": None if is_docuseal else profile.last_induction,
                    "checked_at": None if is_docuseal else profile.last_induction,
                    "external_reference": (
                        str(profile.memberdoc_id)
                        if is_docuseal and profile.memberdoc_id
                        else ""
                    ),
                },
            )


class Migration(migrations.Migration):

    dependencies = [
        ("profile", "0028_profile_memberdoc_url"),
    ]

    operations = [
        migrations.CreateModel(
            name="InductionProviderState",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "provider",
                    models.CharField(
                        choices=[
                            ("canvas", "Canvas"),
                            ("moodle", "Moodle"),
                            ("docuseal", "DocuSeal"),
                        ],
                        max_length=20,
                    ),
                ),
                ("requirement_key", models.CharField(max_length=255)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("complete", "Complete"),
                            ("declined", "Declined"),
                            ("unavailable", "Unavailable"),
                            ("invalid_configuration", "Invalid configuration"),
                        ],
                        default="pending",
                        max_length=32,
                    ),
                ),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("checked_at", models.DateTimeField(blank=True, null=True)),
                ("score", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("error_code", models.CharField(blank=True, max_length=64)),
                ("external_reference", models.CharField(blank=True, max_length=255)),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="induction_provider_states",
                        to="profile.profile",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="inductionproviderstate",
            constraint=models.UniqueConstraint(
                fields=("profile", "provider", "requirement_key"),
                name="unique_profile_induction_requirement",
            ),
        ),
        migrations.RunPython(
            backfill_valid_legacy_induction, migrations.RunPython.noop
        ),
    ]
