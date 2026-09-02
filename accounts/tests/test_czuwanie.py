"""
Alert o tym, że chatbot klienta przestał odpowiadać.

Kategoria ryzyka: CISZA. Raport z 26.08.2026 kończy się zdaniem „The check
that found this was manual. A step on a checklist a person walks through is
not detection." Te testy pilnują, żeby wiadomość poszła bez udziału człowieka
- i, co równie ważne, żeby NIE szła wtedy, gdy nic się nie stało.

Alert, który przychodzi za często, przestaje być czytany. Wtedy prawdziwa
awaria też zostaje przeoczona i wracamy dokładnie tam, skąd wyszliśmy.
"""

from unittest.mock import patch

import pytest
from django.core import mail
from django.utils import timezone

from accounts.czuwanie import PROG_ZLYCH_KLUCZY, sprawdz_odmowy_widgetu
from accounts.models import Tenant
from accounts.odmowy import PowodOdmowy, ZliczenieOdmow


@pytest.fixture
def firma(db):
    return Tenant.objects.create(name="Rowerownia", owner_email="szef@rowerownia.pl")


def odmowy(tenant, powod, liczba=1, dzien=None):
    teraz = timezone.now()
    return ZliczenieOdmow.objects.create(
        tenant=tenant,
        powod=powod,
        dzien=dzien or timezone.localdate(),
        liczba=liczba,
        pierwsza=teraz,
        ostatnia=teraz,
    )


@pytest.mark.django_db
class TestKiedyAlarmuje:
    def test_wygasla_subskrypcja_alarmuje_od_pierwszej_odmowy(self, firma):
        """
        Dokładnie przypadek z sierpnia.

        Jedna odmowa to jeden odwiedzajacy, ktory otworzyl czat i nie dostal
        odpowiedzi. Czekanie na "wieksza probke" znaczyloby czekanie, az wiecej
        ludzi odejdzie z niczym.
        """
        odmowy(firma, PowodOdmowy.SUBSKRYPCJA_WYGASLA, liczba=1)

        assert sprawdz_odmowy_widgetu() == 1
        assert len(mail.outbox) == 1
        assert "Rowerownia" in mail.outbox[0].body
        assert "Subskrypcja poza datami" in mail.outbox[0].body

    def test_brak_subskrypcji_tez_alarmuje(self, firma):
        odmowy(firma, PowodOdmowy.BRAK_SUBSKRYPCJI)

        assert sprawdz_odmowy_widgetu() == 1

    def test_wiadomosc_mowi_ilu_ludzi_to_dotknelo(self, firma):
        # To jest liczba, ktorej raport z incydentu nie umial podac.
        odmowy(firma, PowodOdmowy.SUBSKRYPCJA_WYGASLA, liczba=137)

        sprawdz_odmowy_widgetu()

        assert "137" in mail.outbox[0].body


@pytest.mark.django_db
class TestKiedyMilczy:
    def test_wyczerpany_limit_nie_alarmuje_operatora(self, firma):
        """
        Wyczerpanie limitu to normalny koniec cyklu, nie awaria.

        Wlasciciel dostaje o nim wlasne maile przy 80, 95 i 100 procentach
        zuzycia. Dublowanie tego alertem do operatora zamienicby powiadomienia
        w szum, przez ktory przestaloby sie widziec te wazne.
        """
        odmowy(firma, PowodOdmowy.LIMIT_WIADOMOSCI, liczba=500)

        assert sprawdz_odmowy_widgetu() == 0
        assert len(mail.outbox) == 0

    def test_pojedynczy_zly_klucz_nie_alarmuje(self, db):
        # Skaner, stary fragment na czyjejs porzuconej stronie, czyjs test.
        odmowy(None, PowodOdmowy.ZLY_KLUCZ, liczba=3)

        assert sprawdz_odmowy_widgetu() == 0
        assert len(mail.outbox) == 0

    def test_seria_zlych_kluczy_juz_alarmuje(self, db):
        # Powyzej progu to zwykle klient, ktory wklein fragment z literowka
        # w kluczu - jego czat jest martwy od pierwszej minuty.
        odmowy(None, PowodOdmowy.ZLY_KLUCZ, liczba=PROG_ZLYCH_KLUCZY)

        assert sprawdz_odmowy_widgetu() == 1
        assert "nieznana firma" in mail.outbox[0].body

    def test_trwajaca_awaria_nie_alarmuje_co_godzine(self, firma):
        """
        Zadanie chodzi co godzine. Bez znacznika ta sama awaria wyslalaby
        24 maile na dobe i nauczylaby nas je kasowac bez czytania.
        """
        odmowy(firma, PowodOdmowy.SUBSKRYPCJA_WYGASLA)

        assert sprawdz_odmowy_widgetu() == 1
        assert sprawdz_odmowy_widgetu() == 0
        assert sprawdz_odmowy_widgetu() == 0
        assert len(mail.outbox) == 1

    def test_nastepnego_dnia_przypomina(self, firma):
        """
        Chatbot milczacy siodmy dzien ma sie odezwac siodmy raz.

        Znacznik jest przypiety do wiersza, czyli do pary firma-powod-dzien.
        Nowy dzien to nowy wiersz, wiec przypomnienie przychodzi raz na dobe,
        dopoki trwa przyczyna - a nie tylko pierwszego dnia.
        """
        wczoraj = timezone.localdate() - timezone.timedelta(days=1)
        wpis = odmowy(firma, PowodOdmowy.SUBSKRYPCJA_WYGASLA, dzien=wczoraj)
        wpis.zgloszone = True
        wpis.save()

        odmowy(firma, PowodOdmowy.SUBSKRYPCJA_WYGASLA)

        assert sprawdz_odmowy_widgetu() == 1

    def test_wczorajsze_niezgloszone_nie_wraca(self, firma):
        # Alert o awarii sprzed doby nie jest alertem, tylko archeologia.
        # Zadanie patrzy wylacznie na dzis.
        wczoraj = timezone.localdate() - timezone.timedelta(days=1)
        odmowy(firma, PowodOdmowy.SUBSKRYPCJA_WYGASLA, dzien=wczoraj)

        assert sprawdz_odmowy_widgetu() == 0

    def test_brak_odmow_to_brak_maila(self, firma):
        assert sprawdz_odmowy_widgetu() == 0
        assert len(mail.outbox) == 0


@pytest.mark.django_db
class TestNiezawodnosci:
    def test_nieudana_wysylka_nie_stawia_znacznika(self, firma):
        """
        Najważniejszy test w tym pliku.

        Gdyby znacznik szedl przed wysylka, awaria poczty kasowalaby alert na
        zawsze: nastepne uruchomienie uznaloby sprawe za zalatwiona i chatbot
        milczalby dalej, tyle ze teraz takze w powiadomieniach. Zamiast tego
        wyjatek leci dalej, a Celery ponowi za godzine.
        """
        odmowy(firma, PowodOdmowy.SUBSKRYPCJA_WYGASLA)

        with patch("accounts.czuwanie.send_mail", side_effect=RuntimeError("SMTP nie odpowiada")):
            with pytest.raises(RuntimeError):
                sprawdz_odmowy_widgetu()

        assert ZliczenieOdmow.objects.get().zgloszone is False

        # Po ustaniu awarii poczty alert wychodzi normalnie.
        assert sprawdz_odmowy_widgetu() == 1
        assert len(mail.outbox) == 1

    def test_kilka_firm_w_jednej_wiadomosci(self, db):
        pierwsza = Tenant.objects.create(name="Rowerownia", owner_email="a@example.com")
        druga = Tenant.objects.create(name="Piekarnia", owner_email="b@example.com")
        odmowy(pierwsza, PowodOdmowy.SUBSKRYPCJA_WYGASLA)
        odmowy(druga, PowodOdmowy.BRAK_SUBSKRYPCJI)

        assert sprawdz_odmowy_widgetu() == 2

        # Jedna wiadomosc, nie dwie: przy szerszej awarii - wygasly certyfikat,
        # zla migracja - kazda firma z osobna zalalaby skrzynke i utrudnila
        # zobaczenie, ze to jedno zdarzenie, a nie dwadziescia.
        assert len(mail.outbox) == 1
        assert "Rowerownia" in mail.outbox[0].body
        assert "Piekarnia" in mail.outbox[0].body
