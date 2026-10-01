from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0044_trwale_usuwanie_plikow")]

    operations = [
        migrations.CreateModel(
            name="PrzebiegMonitora",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("wyslano_at", models.DateTimeField()),
            ],
        ),
    ]
