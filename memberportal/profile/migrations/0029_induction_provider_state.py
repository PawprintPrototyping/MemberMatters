from django.db import migrations, models
import django.db.models.deletion


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
    ]
