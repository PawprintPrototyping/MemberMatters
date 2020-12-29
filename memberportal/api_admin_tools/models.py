from django.db import models


class MemberTier(models.Model):
    """[A membership tier that a member can be billed for.]
    """
    name = models.CharField("Name", max_length=30, unique=True)
    description = models.CharField("Description", max_length=50, unique=True)
    stripe_id = models.CharField("Stripe Id", max_length=100, unique=True)
    visible = models.BooleanField("Is this plan visible to members?", default=True)

    def __str__(self):
        return self.name


class PaymentPlan(models.Model):
    """[A payment plan that specifies how a member is billed for a member tier.]
    """
    BILLING_PERIODS = [
        ("Months", "months"),
        ("Weeks", "weeks"),
        ("Days", "days")
    ]

    name = models.CharField("Name", max_length=30, unique=True)
    stripe_id = models.CharField("Stripe Id", max_length=100, unique=True)
    member_tier = models.ForeignKey(MemberTier, on_delete=models.CASCADE)
    visible = models.BooleanField("Is this plan visible to members?", default=True)

    cost = models.IntegerField("The cost in cents for this payment plan.")
    interval = models.IntegerField("The interval the price is charged at (per billing period).")
    period = models.CharField(choices=BILLING_PERIODS, max_length=10)

    def __str__(self):
        return self.name