import json

from constance.codecs import dumps, loads
from django.db import migrations, transaction

LEGACY_EMAIL_KEYS = (
    "POSTMARK_API_KEY",
    "SMTP_HOSTNAME",
    "SMTP_PORT",
    "SMTP_USE_TLS",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
)
TARGET_EMAIL_KEYS = (
    "EMAIL_BACKEND_OPTIONS",
    "EMAIL_BACKEND",
    "EMAIL_ENABLED",
)
PLACEHOLDER_VALUES = {"", "PLEASE_CHANGE_ME"}


def _configured_string(value):
    if not isinstance(value, str):
        return ""

    value = value.strip()
    return "" if value in PLACEHOLDER_VALUES else value


def _smtp_port(value):
    try:
        port = int(value)
    except (TypeError, ValueError):
        return 587
    return port if 0 < port < 65536 else 587


def _smtp_use_tls(value):
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def migrate_email_backend_configuration(apps, schema_editor):
    Constance = apps.get_model("constance", "Constance")
    if (
        schema_editor is not None
        and Constance._meta.db_table
        not in schema_editor.connection.introspection.table_names()
    ):
        return

    legacy_values = {
        setting.key: loads(setting.value)
        for setting in Constance.objects.filter(key__in=LEGACY_EMAIL_KEYS)
    }

    profiles = {}
    postmark_token = _configured_string(legacy_values.get("POSTMARK_API_KEY"))
    if postmark_token:
        profiles["postmark"] = {"server_token": postmark_token}

    smtp_host = _configured_string(legacy_values.get("SMTP_HOSTNAME"))
    if smtp_host:
        profiles["smtp"] = {
            "host": smtp_host,
            "port": _smtp_port(legacy_values.get("SMTP_PORT", 587)),
            "username": legacy_values.get("SMTP_USERNAME", "") or "",
            "password": legacy_values.get("SMTP_PASSWORD", "") or "",
            "use_tls": _smtp_use_tls(legacy_values.get("SMTP_USE_TLS", True)),
            "use_ssl": False,
            "timeout": 10,
        }

    if "postmark" in profiles:
        selected_backend = "postmark"
    elif "smtp" in profiles:
        selected_backend = "smtp"
    else:
        selected_backend = "disabled"

    with transaction.atomic():
        target_count = Constance.objects.filter(key__in=TARGET_EMAIL_KEYS).count()
        if target_count == len(TARGET_EMAIL_KEYS):
            Constance.objects.filter(key__in=LEGACY_EMAIL_KEYS).delete()
            return

        # A complete legacy profile takes precedence over a partial new
        # configuration so an existing mail transport keeps working.
        if target_count and not profiles:
            Constance.objects.filter(key__in=LEGACY_EMAIL_KEYS).delete()
            return

        Constance.objects.filter(key__in=TARGET_EMAIL_KEYS).delete()
        Constance.objects.bulk_create(
            [
                Constance(
                    key="EMAIL_BACKEND_OPTIONS",
                    value=dumps(json.dumps(profiles)),
                ),
                Constance(key="EMAIL_BACKEND", value=dumps(selected_backend)),
                Constance(
                    key="EMAIL_ENABLED",
                    value=dumps(selected_backend != "disabled"),
                ),
            ]
        )
        Constance.objects.filter(key__in=LEGACY_EMAIL_KEYS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("profile", "0028_profile_memberdoc_url"),
        ("database", "0002_auto_20190129_2304"),
        ("constance", "0003_drop_pickle"),
    ]

    operations = [
        migrations.RunPython(
            migrate_email_backend_configuration,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
