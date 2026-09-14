from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0038_subscription_stripe"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="anulowanie_od",
            field=models.DateField(
                blank=True,
                help_text="Dzień, w którym Stripe zakończy anulowaną subskrypcję.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="subscription",
            name="zaplanowany_plan",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Plan kolejnej fazy harmonogramu Stripe, np. po obniżce.",
                max_length=50,
            ),
        ),
        migrations.AddField(
            model_name="subscription",
            name="zaplanowany_plan_od",
            field=models.DateField(
                blank=True, help_text="Od kiedy obowiązuje zaplanowany plan.", null=True
            ),
        ),
    ]
