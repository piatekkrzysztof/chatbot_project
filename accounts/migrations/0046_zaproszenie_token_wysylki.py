"""
Drugi klucz zaproszenia: link do przekazania, który nie zakłada konta.

Trzy kroki zamiast jednego `AddField`. Pole z `default=uuid.uuid4` i `unique`
dodane wprost dostałoby we wszystkich istniejących wierszach TĘ SAMĄ wartość -
Django wylicza wartość domyślną raz na migrację, nie raz na wiersz - i migracja
wywróciłaby się na ograniczeniu unikalności przy drugim zaproszeniu w bazie.

Istniejące zaproszenia dostają nowy klucz wysyłki, a ich klucz przyjęcia
zostaje bez zmian. Linki skopiowane z panelu przed wdrożeniem nadal więc
zakładają konto, dopóki zaproszenie nie wygaśnie - najdłużej 7 dni. Nie
unieważniamy ich na siłę: zepsułoby to zaproszenia w drodze, a ryzyko kończy
się samo w ciągu tygodnia.
"""

import uuid

from django.db import migrations, models


def nadaj_klucze_wysylki(apps, schema_editor):
    InvitationToken = apps.get_model("accounts", "InvitationToken")
    for zaproszenie in InvitationToken.objects.filter(token_wysylki__isnull=True).only("pk"):
        InvitationToken.objects.filter(pk=zaproszenie.pk).update(token_wysylki=uuid.uuid4())


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0045_przebieg_monitora"),
    ]

    operations = [
        migrations.AddField(
            model_name="invitationtoken",
            name="token_wysylki",
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.RunPython(nadaj_klucze_wysylki, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="invitationtoken",
            name="token_wysylki",
            field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False),
        ),
    ]
