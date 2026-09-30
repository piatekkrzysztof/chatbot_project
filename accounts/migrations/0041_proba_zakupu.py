import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def oznacz_istniejace_firmy(apps, schema_editor):
    Tenant = apps.get_model("accounts", "Tenant")
    Proba = apps.get_model("accounts", "ProbaZakupu")
    alias = schema_editor.connection.alias
    for tenant_id in Tenant.objects.using(alias).values_list("pk", flat=True).iterator():
        Proba.objects.using(alias).get_or_create(
            tenant_id=tenant_id, defaults={"sprawdzone_stare_sesje": False}
        )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0040_skrot_skrzynki")]
    operations = [
        migrations.CreateModel(
            name="ProbaZakupu",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("klucz", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("parametry", models.JSONField(blank=True, default=dict)),
                ("sesja_id", models.CharField(blank=True, max_length=255)),
                ("rozpoczeta_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("sprawdzone_stare_sesje", models.BooleanField(default=True)),
                (
                    "tenant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="proba_zakupu",
                        to="accounts.tenant",
                    ),
                ),
            ],
        ),
        migrations.RunPython(oznacz_istniejace_firmy, migrations.RunPython.noop),
    ]
