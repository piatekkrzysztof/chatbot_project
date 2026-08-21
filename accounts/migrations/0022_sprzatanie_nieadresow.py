"""
Usuwa z rejestru witryn wpisy, które adresem nie są.

Na produkcji jeden klient miał zapisaną "domenę" o nazwie `null` — tyle
wysyła przeglądarka w nagłówku Origin ze stron w piaskownicy, z plików
otwartych z dysku i z części przekierowań. W panelu wyglądało to jak
prawdziwa witryna i zajmowało miejsce w limicie planu.

Samą przyczynę naprawia `wyglada_na_adres_witryny` w accounts/domains.py.
Ta migracja sprząta to, co zdążyło się zapisać wcześniej — łącznie z oknem
między naprawą a jej wdrożeniem.
"""
from django.db import migrations

# Świadomie tylko dokładne dopasowanie, bez sprytniejszych reguł: migracja
# kasuje dane bez pytania, więc ma trafiać wyłącznie w wartości, o których
# wiadomo na pewno, że adresem nie są. Hosty wewnętrzne bez kropki zostawiamy —
# nowe już nie powstaną, a stary wpis może być czymś, o czym nie wiemy.
NIE_ADRESY = ["null", "undefined", "none", "about", "blank"]


def posprzataj(apps, schema_editor):
    WidgetDomain = apps.get_model("accounts", "WidgetDomain")
    WidgetDomain.objects.filter(host__in=NIE_ADRESY).delete()


def bez_cofania(apps, schema_editor):
    """Nie odtwarzamy — to były śmieci, nie dane."""


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0021_raport_tygodniowy"),
    ]

    operations = [
        migrations.RunPython(posprzataj, bez_cofania),
    ]
