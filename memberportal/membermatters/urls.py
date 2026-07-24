"""membermatters URL Configuration"""

import os
import django.db.utils
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from constance import config
import json
from asgiref.sync import sync_to_async


@sync_to_async
def safe_constance_get(fld: str):
    return getattr(config, fld)


# Initialise Sentry for backend error reporting. Skipped when:
#   * no DSN is configured (default),
#   * MM_ENV is unset or set to "Development"
#   * the constance table isn't yet available (e.g. first-run migrations).
try:
    SENTRY_DSN_BACKEND = getattr(config, "SENTRY_DSN_BACKEND", "")
    if (
        SENTRY_DSN_BACKEND
        and os.environ.get("MM_ENV")
        and os.environ.get("MM_ENV") != "Development"
    ):
        release = None
        try:
            with open("../package.json") as f:
                release = json.load(f).get("version")
        except (OSError, ValueError):
            pass

        sentry_sdk.init(
            release=os.environ.get("SENTRY_RELEASE", release),
            environment=os.environ.get("SENTRY_ENVIRONMENT", os.environ.get("MM_ENV", "Development")),
            dsn=SENTRY_DSN_BACKEND,
            integrations=[DjangoIntegration()],
        )
except django.db.utils.OperationalError:
    pass

urlpatterns = [
    path("api/openid/", include("oidc_provider.urls", namespace="oidc_provider")),
    path("", include("api_metrics.urls")),
    path("", include("api_spacedirectory.urls")),
    path("", include("api_general.urls")),
    path("", include("api_access.urls")),
    path("", include("api_member_tools.urls")),
    path("", include("api_meeting.urls")),
    path("", include("api_member_bucks.urls")),
    path("", include("api_billing.urls")),
    path("", include("api_admin_tools.urls")),
    path("api/", include("django_prometheus.urls")),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root="")
