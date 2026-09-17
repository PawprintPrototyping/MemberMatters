from django.db import migrations, models
from django.utils import timezone


class AddFieldIfMissing(migrations.AddField):
    """Advance model state while tolerating the two released 0029 schemas."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        to_model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, to_model):
            return

        field = to_model._meta.get_field(self.name)
        with schema_editor.connection.cursor() as cursor:
            columns = {
                description.name
                for description in schema_editor.connection.introspection.get_table_description(
                    cursor, to_model._meta.db_table
                )
            }
        if field.column in columns:
            return

        super().database_forwards(app_label, schema_editor, from_state, to_state)


def backfill_valid_legacy_induction(apps, schema_editor):
    """Store the lossy legacy timestamp as explicit compatibility evidence."""
    Profile = apps.get_model("profile", "Profile")
    InductionProviderState = apps.get_model("profile", "InductionProviderState")

    for profile in Profile.objects.exclude(last_induction__isnull=True):
        # The timestamp contains no provider, course, score, or document
        # provenance. Runtime code consumes it only for the LMS selected by
        # the old Moodle-over-Canvas flow; it never satisfies DocuSeal.
        InductionProviderState.objects.get_or_create(
            profile_id=profile.pk,
            provider="legacy",
            requirement_key="legacy:last-induction",
            defaults={
                "status": "complete",
                "completed_at": profile.last_induction,
                "checked_at": profile.last_induction,
                "external_reference": "",
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("profile", "0031_merge_20260916_1458"),
    ]

    operations = [
        AddFieldIfMissing(
            model_name="inductionproviderstate",
            name="external_reference",
            field=models.CharField(blank=True, default="", max_length=255),
            preserve_default=False,
        ),
        migrations.RunPython(
            backfill_valid_legacy_induction, migrations.RunPython.noop
        ),
    ]
