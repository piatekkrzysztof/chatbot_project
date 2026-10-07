"""
Pojemność procesu web dzielona między firmy - 2.24.0.

Kategoria ryzyka: JEDEN KLIENT WYŁĄCZA WSZYSTKICH. Do 2.24.0 proces miał dwa
miejsca na rozmowy wspólne dla wszystkich firm. Jedna firma z ruchem - albo
ktoś, kto przez publiczny klucz widgetu trzymał dwie długie rozmowy - zajmowała
oba, a widgety pozostałych klientów odpowiadały 503. Nikt się o tym nie
dowiadywał: odmów nie liczono i nie było alarmu.

Testy pilnują trzech rzeczy: firma nie zajmie wszystkich miejsc, odmowy są
policzone i od progu alarmują, a zapis samych kolorów brandingu nie czeka na
cudzy upload.
"""

import importlib
from unittest.mock import patch

import pytest
from django.core import mail
from rest_framework.test import APIClient

from accounts.czuwanie import PROG_ODMOW_POJEMNOSCI, sprawdz_odmowy_widgetu
from accounts.models import Subscription, Tenant
from accounts.odmowy import PowodOdmowy, ZliczenieOdmow
from api import capacity

pytestmark = pytest.mark.django_db(transaction=True)

SESJA = "cf236f5b-8082-4513-b8a5-7941f4557f10"


@pytest.fixture
def pule(monkeypatch):
    rozmowy = capacity.Pula(3, 2)
    monkeypatch.setattr(capacity, "CHAT_SLOTS", rozmowy)
    monkeypatch.setattr(capacity, "UPLOAD_SLOTS", capacity.Pula(1, 1))
    return rozmowy


def firma_z_planem(nazwa):
    from datetime import date, timedelta

    tenant = Tenant.objects.create(name=nazwa, owner_email=f"{nazwa}@example.com")
    Subscription.objects.create(
        tenant=tenant,
        plan_type="pro",
        is_active=True,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=30),
    )
    return tenant


def zapytaj_widget(tenant):
    return APIClient().post(
        "/api/widget/chat/stream/",
        {"message": "Ile kosztuje tort?", "conversation_session_id": SESJA},
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
    )


def test_jedna_firma_nie_zajmie_wszystkich_miejsc(pule):
    """Ten test padał przed 2.24.0: trzecia rozmowa tej samej firmy wchodziła."""
    assert pule.zajmij("A") is None
    assert pule.zajmij("A") is None

    assert pule.zajmij("A") == PowodOdmowy.LIMIT_ROZMOW_FIRMY
    assert pule.zajmij("B") is None
    assert pule.zajmij("C") == PowodOdmowy.SERWER_ZAJETY

    pule.zwolnij("A")
    assert pule.zajmij("A") is None


def test_zwolnienie_firmy_nie_zostawia_sladu(pule):
    """Firma, która skończyła rozmowy, nie może blokować się licznikiem z przeszłości."""
    for _ in range(2):
        assert pule.zajmij("A") is None
    for _ in range(2):
        pule.zwolnij("A")

    assert pule.zajete == 0
    assert pule.firmy == {}


def test_widget_firmy_z_ruchem_odmawia_a_innej_firmy_nie(pule):
    """Przez HTTP: limit liczy się dla firmy z klucza widgetu, nie dla wszystkich."""
    zajeta = firma_z_planem("zajeta")
    wolna = firma_z_planem("wolna")
    assert pule.zajmij(zajeta.pk) is None
    assert pule.zajmij(zajeta.pk) is None

    odmowa = zapytaj_widget(zajeta)
    with patch("api.views.widget.stream_chat_message", return_value=iter([b"data: {}\n\n"])):
        przyjeta = zapytaj_widget(wolna)

    assert odmowa.status_code == 503
    assert odmowa.data["code"] == "server_busy"
    assert przyjeta.status_code == 200
    przyjeta.close()
    assert ZliczenieOdmow.objects.get(tenant=zajeta).powod == PowodOdmowy.LIMIT_ROZMOW_FIRMY
    assert not ZliczenieOdmow.objects.filter(tenant=wolna).exists()


def test_pelny_serwer_jest_liczony_osobno(pule):
    """Pełny serwer i limit firmy to różne decyzje: większa instancja albo rozmowa z klientem."""
    for firma in ("x", "y", "z"):
        assert pule.zajmij(firma) is None
    tenant = firma_z_planem("pechowa")

    for _ in range(3):
        assert zapytaj_widget(tenant).status_code == 503

    zliczenie = ZliczenieOdmow.objects.get(tenant=tenant)
    assert (zliczenie.powod, zliczenie.liczba) == (PowodOdmowy.SERWER_ZAJETY, 3)


def test_awaria_licznika_nie_zamienia_odmowy_w_blad_serwera(pule):
    for firma in ("x", "y", "z"):
        assert pule.zajmij(firma) is None
    tenant = firma_z_planem("bez-licznika")

    with patch("api.capacity.zapisz_odmowe", side_effect=RuntimeError("baza padła")):
        odpowiedz = zapytaj_widget(tenant)

    assert odpowiedz.status_code == 503


@pytest.mark.parametrize("powod", [PowodOdmowy.SERWER_ZAJETY, PowodOdmowy.LIMIT_ROZMOW_FIRMY])
def test_alarm_dopiero_od_progu(settings, powod):
    """Pojedyncze odmowy widget ponawia sam - mail dopiero przy serii."""
    from django.utils import timezone

    settings.EMAIL_ALERTOW = "alerty@example.com"
    tenant = Tenant.objects.create(name="Cukiernia", owner_email="c@example.com")
    teraz = timezone.now()
    zliczenie = ZliczenieOdmow.objects.create(
        tenant=tenant,
        powod=powod,
        dzien=timezone.localdate(),
        liczba=PROG_ODMOW_POJEMNOSCI - 1,
        pierwsza=teraz,
        ostatnia=teraz,
    )

    assert sprawdz_odmowy_widgetu() == 0
    assert mail.outbox == []

    zliczenie.liczba = PROG_ODMOW_POJEMNOSCI
    zliczenie.save()

    assert sprawdz_odmowy_widgetu() == 1
    assert "Cukiernia" in mail.outbox[0].body


def test_zapis_kolorow_nie_czeka_na_cudzy_upload(pule, user, tenant, subscribtion):
    """Ten test padał przed 2.24.0: PATCH bez pliku dostawał 503, gdy ktoś wgrywał PDF."""
    user.role = "owner"
    user.save()
    klient = APIClient()
    klient.force_authenticate(user=user)
    klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))
    assert capacity.UPLOAD_SLOTS.zajmij("ktos-inny") is None

    kolory = klient.patch(
        "/api/widget-settings/mine/", {"widget_title": "Cukiernia"}, format="json"
    )
    z_plikiem = klient.patch(
        "/api/widget-settings/mine/", {"widget_title": "Cukiernia"}, format="multipart"
    )

    assert kolory.status_code == 200
    assert z_plikiem.status_code == 503


def test_watki_gunicorna_zostawiaja_miejsce_nad_ciezkimi_zadaniami(monkeypatch):
    """Podniesienie limitu rozmów bez wątków zjadłoby wątki panelu."""
    import chatbot_project.gunicorn_config as profil
    import chatbot_project.pojemnosc as pojemnosc

    monkeypatch.setenv("POJEMNOSC_ROZMOW", "9")
    monkeypatch.setenv("POJEMNOSC_UPLOADOW", "2")
    try:
        importlib.reload(pojemnosc)
        importlib.reload(profil)
        assert profil.threads == 9 + 2 + pojemnosc.WATKI_LEKKIE
        assert pojemnosc.WATKI_LEKKIE >= 2
    finally:
        monkeypatch.delenv("POJEMNOSC_ROZMOW")
        monkeypatch.delenv("POJEMNOSC_UPLOADOW")
        importlib.reload(pojemnosc)
        importlib.reload(profil)


def test_domyslne_liczby_z_pomiaru_sa_przypiete():
    """Zmiana tych liczb zmienia czas odpowiedzi wszystkich klientów - to decyzja z pomiarem."""
    import chatbot_project.gunicorn_config as profil
    import chatbot_project.pojemnosc as pojemnosc

    assert (pojemnosc.ROZMOWY, pojemnosc.ROZMOWY_FIRMY, pojemnosc.UPLOADY) == (6, 3, 1)
    assert profil.threads == 10
    assert profil.workers == 1
