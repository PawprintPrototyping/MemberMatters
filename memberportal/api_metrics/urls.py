import os

from django.urls import include, path
from rest_framework_simplejwt import views as jwt_views
from health_check.views import HealthCheckView
from . import views

node_checks: list[str] = [
    "health_check.contrib.psutil.CPU",
    "health_check.contrib.psutil.Memory",
    "health_check.contrib.psutil.Disk",
]

app_checks: list[str] = [
    "health_check.Cache",
    "health_check.DNS",
    "health_check.Database",
    "health_check.Mail",
    "health_check.Storage",
    "health_check.contrib.celery.Ping",
    "health_check.contrib.crontask.Scheduler",
]

urlpatterns = [
    path(
        "api/statistics/",
        views.Statistics.as_view(),
        name="api_statistics",
    ),
    path(
        "api/update-prom-metrics/",
        views.UpdatePromMetrics.as_view(),
        name="api_update_prom_metrics",
    ),
    path(
        "api/update-statistics/",
        views.UpdateStatistics.as_view(),
        name="api_update_statistics",
    ),
    path(
        f"health/{os.getenv('HEALTH_CHECK_SECRET', 'dev')}/",
        include(
            [
                path(
                    "node/",
                    HealthCheckView.as_view(checks=node_checks),
                    name="health_check-node",
                ),
                path(
                    "app/",
                    HealthCheckView.as_view(checks=app_checks),
                    name="health_check-app",
                ),
            ]
        ),
    ),
]
