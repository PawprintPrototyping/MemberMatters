from django.contrib import admin
from api_metrics.models import Metric


@admin.register(Metric)
class Metric(admin.ModelAdmin):
    pass
