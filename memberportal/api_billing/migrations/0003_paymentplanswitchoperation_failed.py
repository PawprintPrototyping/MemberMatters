from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api_billing", "0002_paymentplanswitchoperation"),
    ]

    operations = [
        migrations.AlterField(
            model_name="paymentplanswitchoperation",
            name="status",
            field=models.CharField(
                choices=[("pending", "Pending"), ("failed", "Failed")],
                default="pending",
                max_length=16,
            ),
        ),
    ]
