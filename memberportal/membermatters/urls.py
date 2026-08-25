"""membermatters URL Configuration"""

from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from constance import config
from asgiref.sync import sync_to_async


@sync_to_async
def safe_constance_get(fld: str):
    return getattr(config, fld)


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
