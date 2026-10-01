from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("api_admin_tools", "0013_paymentplan_description"),
        ("api_billing", "0001_initial"),
        ("constance", "0003_drop_pickle"),
        ("profile", "0033_alter_inductionproviderstate_provider"),
    ]

    operations = [
        migrations.CreateModel(
            name="PaymentPlanSwitchOperation",
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
                ("stripe_subscription_id", models.CharField(max_length=100)),
                ("idempotency_key", models.CharField(max_length=255, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "Pending")],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("last_error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "current_plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="switch_operations_from",
                        to="api_admin_tools.paymentplan",
                    ),
                ),
                (
                    "profile",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payment_plan_switch_operation",
                        to="profile.profile",
                    ),
                ),
                (
                    "target_plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="switch_operations_to",
                        to="api_admin_tools.paymentplan",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["status", "updated_at"],
                        name="api_billing_status_55ab81_idx",
                    )
                ],
            },
        ),
    ]
