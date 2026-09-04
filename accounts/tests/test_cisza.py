"""
Alert o chatbocie, który zamilkł.

Kategoria ryzyka: FAŁSZYWY ALARM. Ten sygnał jest ze wszystkich naszych
najbardziej podatny na szum, bo cisza bywa zwyczajna: święto, wolniejszy
tydzień, sezon poza sezonem. Alarm, który odzywa się przy każdej z tych
rzeczy, przestaje być czytany - a wtedy przepada także ten prawdziwy.
Dokładnie o tym jest raport z incydentu 26.08.2026.

Dlatego większość tego pliku sprawdza, kiedy alarm ma MILCZEĆ. Testów
„odzywa się, gdy trzeba" jest tu mniej i są łatwiejsze.
"""

from unittest.mock import patch

import pytest
from django.core import mail
from django.utils import timezone

from accounts.cisza import (
    MINIMUM_DNI_Z_RUCHEM,
    OKNO_CISZY,
    ZgloszonaCisza,
    firmy_ktore_zamilkly,
    sprawdz_cisze,
)
from accounts.models import Tenant
from chat.models import Conversation

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def adres_alertow(settings):
    # Wprost, a nie ze srodowiska - ta sama lekcja co w test_czuwanie.py.
    settings.EMAIL_ALERTOW = "alerty@example.com"


@pytest.fixture
def firma(db):
    return Tenant.objects.create(name="Rowerownia", owner_email="szef@rowerownia.pl")


@pytest.fixture
def dzis():
    return timezone.localdate()


def rozmowa(tenant, dzien, zrodlo="widget"):
    """Rozmowa z konkretnego dnia - `started_at` ma auto_now_add, więc nadpisujemy."""
    c = Conversation.objects.create(tenant=tenant, user_identifier="gosc", source=zrodlo)
    Conversation.objects.filter(pk=c.pk).update(
        started_at=timezone.make_aware(
            timezone.datetime.combine(dzien, timezone.datetime.min.time().replace(hour=12))
        )
    )
    return c


def zasil_ruchem(tenant, dzis, dni_z_ruchem, przesuniecie=OKNO_CISZY):
    """
    Ruch w oknie odniesienia: `dni_z_ruchem` kolejnych dni, kończąc tuż przed
    oknem ciszy.
    """
    ostatni = dzis - timezone.timedelta(days=przesuniecie + 1)
    for i in range(dni_z_ruchem):
        rozmowa(tenant, ostatni - timezone.timedelta(days=i))


class TestKiedyMilczy:
    """Najważniejsza klasa w tym pliku."""

    def test_firma_z_rzadkim_ruchem_nie_alarmuje(self, firma, dzis):
        """
        Firma z ruchem przez 10 z 21 dni ma okolo 14 procent szans na trzy
        ciche dni z rzedu. Alarm odzywalby sie u niej co kilka tygodni bez
        zadnego powodu - i nauczylby nas kasowac te wiadomosci bez czytania.
        """
        zasil_ruchem(firma, dzis, dni_z_ruchem=10)

        assert firmy_ktore_zamilkly(dzis) == []

    def test_prog_gestosci_jest_dokladnie_tam_gdzie_deklarujemy(self, firma, dzis):
        # O jeden dzien za malo - milczy.
        zasil_ruchem(firma, dzis, dni_z_ruchem=MINIMUM_DNI_Z_RUCHEM - 1)
        assert firmy_ktore_zamilkly(dzis) == []

        # Dokladnie prog - odzywa sie.
        rozmowa(firma, dzis - timezone.timedelta(days=OKNO_CISZY + MINIMUM_DNI_Z_RUCHEM + 1))
        assert len(firmy_ktore_zamilkly(dzis)) == 1

    def test_jeden_cichy_dzien_nie_wystarcza(self, firma, dzis):
        # Swieto, awaria u dostawcy klienta, cokolwiek. Za malo, zeby pisac.
        zasil_ruchem(firma, dzis, dni_z_ruchem=21, przesuniecie=1)

        assert firmy_ktore_zamilkly(dzis) == []

    def test_ruch_w_oknie_ciszy_konczy_sprawe(self, firma, dzis):
        zasil_ruchem(firma, dzis, dni_z_ruchem=21)
        rozmowa(firma, dzis - timezone.timedelta(days=2))

        assert firmy_ktore_zamilkly(dzis) == []

    def test_rozmowy_z_panelu_nie_licza_sie_jako_zycie(self, firma, dzis):
        """
        Wlasciciel klikajacy codziennie „Test bota" wygladalby na zywego przy
        zupelnie martwym widgecie. To jest dokladnie ta awaria, ktorej szukamy,
        wiec liczenie testow zamaskowaloby ja najskuteczniej.
        """
        zasil_ruchem(firma, dzis, dni_z_ruchem=21)
        for i in range(OKNO_CISZY):
            rozmowa(firma, dzis - timezone.timedelta(days=i + 1), zrodlo="panel")

        assert len(firmy_ktore_zamilkly(dzis)) == 1

    def test_dzisiejszy_dzien_nie_jest_liczony(self, firma, dzis):
        # Dzis jeszcze trwa i jego pustka o poranku niczego nie znaczy.
        zasil_ruchem(firma, dzis, dni_z_ruchem=21, przesuniecie=0)

        assert firmy_ktore_zamilkly(dzis) == []

    def test_nowa_firma_bez_historii_nie_alarmuje(self, firma, dzis):
        # Konto zalozone wczoraj nie ma jak miec 18 dni ruchu.
        assert firmy_ktore_zamilkly(dzis) == []


class TestKiedyAlarmuje:
    def test_firma_z_gestym_ruchem_ktora_zamilkla(self, firma, dzis):
        zasil_ruchem(firma, dzis, dni_z_ruchem=21)

        znalezione = firmy_ktore_zamilkly(dzis)

        assert len(znalezione) == 1
        assert znalezione[0]["tenant"] == firma
        assert znalezione[0]["dni_ciszy"] == OKNO_CISZY

    def test_wiadomosc_mowi_od_kiedy_i_ile_bylo_wczesniej(self, firma, dzis):
        zasil_ruchem(firma, dzis, dni_z_ruchem=21)

        assert sprawdz_cisze(dzis) == 1
        tresc = mail.outbox[0].body
        assert "Rowerownia" in tresc
        # Bez liczb wiadomosc mowi "cos jest nie tak" i nie daje sie ocenic.
        assert "21" in tresc
        # Podpowiedz, co sprawdzic - alert bez tego zostawia odbiorce
        # z pytaniem "i co teraz".
        assert "stron" in tresc.lower()


class TestPonawiania:
    def test_ta_sama_cisza_zglasza_sie_raz(self, firma, dzis):
        """
        Zadanie chodzi codziennie. Bez znacznika ta sama martwa firma
        wysylalaby wiadomosc kazdego ranka, dopoki ktos by nie zareagowal -
        czyli najglosniej wtedy, gdy juz o niej wiemy.
        """
        zasil_ruchem(firma, dzis, dni_z_ruchem=21)

        assert sprawdz_cisze(dzis) == 1
        assert sprawdz_cisze(dzis) == 0
        assert sprawdz_cisze(dzis + timezone.timedelta(days=1)) == 0
        assert len(mail.outbox) == 1

    def test_cisza_po_powrocie_ruchu_zglasza_sie_na_nowo(self, firma, dzis):
        # Inny poczatek ciszy to inne zdarzenie, nie to samo trwajace.
        zasil_ruchem(firma, dzis, dni_z_ruchem=21)
        assert sprawdz_cisze(dzis) == 1

        # Ruch wraca na jeden dzien, potem znowu cisza.
        pozniej = dzis + timezone.timedelta(days=4)
        rozmowa(firma, dzis)

        assert sprawdz_cisze(pozniej) == 1
        assert len(mail.outbox) == 2

    def test_nieudana_wysylka_nie_stawia_znacznika(self, firma, dzis):
        """
        Ta sama zasada co przy alercie o odmowach - tam jej brak kosztowal
        osobny blad, znaleziony dopiero przez CI.
        """
        zasil_ruchem(firma, dzis, dni_z_ruchem=21)

        with patch("accounts.cisza.send_mail", side_effect=RuntimeError("SMTP nie odpowiada")):
            with pytest.raises(RuntimeError):
                sprawdz_cisze(dzis)

        assert ZgloszonaCisza.objects.count() == 0
        assert sprawdz_cisze(dzis) == 1

    def test_zero_doreczen_bez_wyjatku_tez_jest_porazka(self, firma, dzis):
        zasil_ruchem(firma, dzis, dni_z_ruchem=21)

        with patch("accounts.cisza.send_mail", return_value=0):
            with pytest.raises(RuntimeError):
                sprawdz_cisze(dzis)

        assert ZgloszonaCisza.objects.count() == 0


class TestWieluFirm:
    def test_kazda_firma_oceniana_osobno(self, db, dzis):
        zywa = Tenant.objects.create(name="Piekarnia", owner_email="a@example.com")
        martwa = Tenant.objects.create(name="Rowerownia", owner_email="b@example.com")

        zasil_ruchem(zywa, dzis, dni_z_ruchem=21)
        rozmowa(zywa, dzis - timezone.timedelta(days=1))
        zasil_ruchem(martwa, dzis, dni_z_ruchem=21)

        znalezione = firmy_ktore_zamilkly(dzis)

        assert [w["tenant"].name for w in znalezione] == ["Rowerownia"]

    def test_kilka_firm_w_jednej_wiadomosci(self, db, dzis):
        for nazwa in ("Rowerownia", "Piekarnia"):
            firma = Tenant.objects.create(name=nazwa, owner_email=f"{nazwa}@example.com")
            zasil_ruchem(firma, dzis, dni_z_ruchem=21)

        assert sprawdz_cisze(dzis) == 2

        # Jedna wiadomosc, nie dwie: przy szerszej awarii kazda firma z osobna
        # zalalaby skrzynke i utrudnila zobaczenie, ze to jedno zdarzenie.
        assert len(mail.outbox) == 1


class TestZadania:
    def test_zadanie_celery_wola_sprawdzenie(self, firma, dzis):
        from accounts.cisza import sprawdz_cisze_zadanie

        with patch("accounts.cisza.sprawdz_cisze", return_value=7) as sprawdzenie:
            assert sprawdz_cisze_zadanie() == 7

        assert sprawdzenie.call_count == 1
