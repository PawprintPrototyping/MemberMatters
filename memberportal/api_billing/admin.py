from django.contrib import admin

from .models import PaymentPlanSwitchOperation


@admin.register(PaymentPlanSwitchOperation)
class PaymentPlanSwitchOperationAdmin(admin.ModelAdmin):
    list_display = (
        "profile",
        "current_plan",
        "target_plan",
        "status",
        "attempt_count",
        "updated_at",
    )
    list_filter = ("status",)
    search_fields = (
        "profile__user__email",
        "stripe_subscription_id",
        "idempotency_key",
    )
    readonly_fields = (
        "profile",
        "current_plan",
        "target_plan",
        "stripe_subscription_id",
        "idempotency_key",
        "status",
        "attempt_count",
        "last_error",
        "created_at",
        "updated_at",
    )

    @admin.action(description="Discard selected failed plan switches")
    def discard_failed_operations(self, request, queryset):
        queryset.filter(status=PaymentPlanSwitchOperation.STATUS_FAILED).delete()

    actions = ("discard_failed_operations",)

    def has_delete_permission(self, request, obj=None):
        return obj is None or obj.status == PaymentPlanSwitchOperation.STATUS_FAILED
