from django.db import migrations, models


class Migration(migrations.Migration):
    """
    F11: wiązanie subskrypcji ze Stripe.

    Dwa pola z wartością domyślną, bez przenoszenia danych. Na dzień migracji
    żadna firma nie ma płatnej subskrypcji w Stripe, więc nie ma czego
    uzupełniać; kolejne zdarzenie Stripe i tak ustawia oba pola.
    """

    dependencies = [
        ("accounts", "0037_password_notification"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="stripe_subscription_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text=(
                    "Identyfikator subskrypcji w Stripe (sub_...). Pusty dla okresu próbnego."
                ),
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="subscription",
            name="stripe_status",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Ostatni znany status subskrypcji w Stripe.",
                max_length=32,
            ),
        ),
    ]
