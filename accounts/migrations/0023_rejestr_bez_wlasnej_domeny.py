"""
Usuwa z rejestru witryn nasz własny adres panelu.

Widget działa w ramce wskazującej na panel, więc zapytania z jej wnętrza
niosą w nagłówku Origin NASZ adres. Rejestr zapisywał go jako kolejną
witrynę klienta: na planie z jedną domeną klient rejestrował własną stronę,
a ramka widgetu próbowała być drugą i dostawała odmowę. Widget tracił wtedy
branding, a klient oglądał w panelu naszą domenę na liście swoich witryn.

Samą przyczynę naprawia `nasz_wlasny_host` w accounts/domains.py. Ta migracja
sprząta wpisy, które zdążyły powstać wcześniej — u każdego klienta, nie tylko
u tego, który to zgłosił.

Adres bierzemy z FRONTEND_URL zamiast wpisywać go tutaj na sztywno: to ta
sama wartość, która służy za źródło ramki, więc migracja trafi we właściwy
host niezależnie od środowiska, w którym się uruchomi.
"""
from django.conf import settings
from django.db import migrations


def posprzataj(apps, schema_editor):
    from accounts.domains import nasz_wlasny_host

    host = nasz_wlasny_host()
    if not host:
        # Brak FRONTEND_URL — nie ma czego szukać i na pewno nie zgadujemy,
        # bo ta migracja kasuje dane bez pytania.
        return

    WidgetDomain = apps.get_model("accounts", "WidgetDomain")
    WidgetDomain.objects.filter(host=host).delete()


def bez_cofania(apps, schema_editor):
    """Nie odtwarzamy — te wpisy nigdy nie powinny były powstać."""


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0022_sprzatanie_nieadresow"),
    ]

    operations = [
        migrations.RunPython(posprzataj, bez_cofania),
    ]
