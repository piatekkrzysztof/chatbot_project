"""
Raport retencji ma mówić to samo, co zrobi usuwanie.

Kategoria ryzyka: DECYZJA NA PODSTAWIE FIKCJI. Ten raport istnieje po to, żeby
właściciel wybrał okresy przechowywania na liczbach zamiast na wyczuciu. Raport,
który liczy innym warunkiem niż komenda usuwająca, jest gorszy niż jego brak:
daje pewność, a prowadzi do decyzji o danych, których nikt nie policzył.

Dlatego najważniejszy test tutaj nie sprawdza żadnej liczby z osobna, tylko
porównuje raport z rzeczywistym przebiegiem istniejących komend `purge_*`.

Drugie ryzyko: wiersz, którego usunąć nie wolno, policzony jako „do usunięcia".
Ważne zaproszenie i niewysłane powiadomienie muszą zostać poza każdym progiem -
pierwsze odebrałoby komuś dostęp do firmy, drugie zgubiłoby wiadomość o zmianie
hasła, czyli jedyny sygnał przy przejęciu konta.
"""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from accounts.management.commands.raport_retencji import (
    raport_dziennika,
    raport_powiadomien,
    raport_rejestracji,
    raport_sesji,
    raport_wyzwan_mfa,
    raport_zaproszen,
)
from accounts.models import (
    CustomUser,
    InvitationToken,
    MfaChallenge,
    PendingRegistration,
    WpisDziennika,
)
from accounts.security_notifications import PasswordNotification
from accounts.sessions import LoginSession

pytestmark = pytest.mark.django_db

DZIEN = timedelta(days=1)


def ile_do_usuniecia(dane, fragment="do usunięcia dziś"):
    return next(ile for opis, ile in dane["progi"] if fragment in opis)


def ile_nietykalnych(dane):
    return sum(ile for _, ile in dane["nietykalne"])


def sesja(uzytkownik, wygasla_przed):
    teraz = timezone.now()
    return LoginSession.objects.create(
        user=uzytkownik,
        password_fingerprint="x" * 64,
        expires_at=teraz - wygasla_przed if wygasla_przed else teraz + 7 * DZIEN,
    )


def wpis_dziennika(ile_dni_temu):
    wpis = WpisDziennika.objects.create(metoda="DELETE", sciezka="/api/faq/1/", status=204)
    # `czas` ma auto_now_add, więc datę trzeba przestawić zapytaniem.
    WpisDziennika.objects.filter(pk=wpis.pk).update(czas=timezone.now() - ile_dni_temu * DZIEN)
    return wpis


def zaproszenie(tenant, *, ile_dni_temu=0, dlugosc="1d", uzyte=0, miejsc=1):
    wpis = InvitationToken.objects.create(
        tenant=tenant, email="ktos@example.com", duration=dlugosc, users=uzyte, max_users=miejsc
    )
    InvitationToken.objects.filter(pk=wpis.pk).update(
        created_at=timezone.now() - ile_dni_temu * DZIEN
    )
    return wpis


class TestZgodnosciZUsuwaniem:
    """Najważniejsza grupa: raport obiecuje dokładnie tyle, ile komenda zabierze."""

    def test_sesje_logowania(self, user):
        sesja(user, 3 * DZIEN)
        sesja(user, 2 * DZIEN)
        sesja(user, timedelta(hours=2))  # wygasła, ale nie minęła doba
        sesja(user, None)  # ważna
        obiecane = ile_do_usuniecia(raport_sesji(timezone.now()))
        przed = LoginSession.objects.count()

        call_command("purge_login_sessions")

        assert obiecane == przed - LoginSession.objects.count() == 2

    def test_wyzwania_drugiego_skladnika(self, user):
        teraz = timezone.now()
        MfaChallenge.objects.create(user=user, fingerprint="a", expires_at=teraz - 3 * DZIEN)
        MfaChallenge.objects.create(
            user=user, fingerprint="b", expires_at=teraz - timedelta(hours=1)
        )
        MfaChallenge.objects.create(user=user, fingerprint="c", expires_at=teraz + DZIEN)
        obiecane = ile_do_usuniecia(raport_wyzwan_mfa(teraz))
        przed = MfaChallenge.objects.count()

        call_command("purge_mfa_challenges")

        assert obiecane == przed - MfaChallenge.objects.count() == 1

    def test_rozpoczete_rejestracje(self):
        teraz = timezone.now()
        for ile_dni, adres in ((10, "stara@example.com"), (2, "swieza@example.com")):
            wpis = PendingRegistration.objects.create(
                email=adres, expires_at=teraz + DZIEN, window_start=teraz
            )
            PendingRegistration.objects.filter(pk=wpis.pk).update(
                created_at=teraz - ile_dni * DZIEN
            )
        obiecane = ile_do_usuniecia(raport_rejestracji(timezone.now()))
        przed = PendingRegistration.objects.count()

        call_command("purge_pending_registrations")

        assert obiecane == przed - PendingRegistration.objects.count() == 1


class TestWierszyNietykalnych:
    def test_wazne_zaproszenie_zostaje_poza_kazdym_progiem(self, tenant):
        zaproszenie(tenant, ile_dni_temu=0, dlugosc="7d")

        dane = raport_zaproszen(timezone.now())

        assert [ile for _, ile in dane["progi"]] == [0, 0, 0]
        assert ile_nietykalnych(dane) == 1

    def test_wykorzystane_zaproszenie_idzie_do_usuniecia_mimo_waznosci(self, tenant):
        # Komplet osób już z niego skorzystał, więc nikomu nie odbierze dostępu.
        zaproszenie(tenant, ile_dni_temu=0, dlugosc="7d", uzyte=1, miejsc=1)

        dane = raport_zaproszen(timezone.now())

        assert ile_do_usuniecia(dane, "nie do użycia już dziś") == 1
        assert ile_nietykalnych(dane) == 0

    def test_zaproszenie_wygasa_wedlug_wlasnej_dlugosci(self, tenant):
        # Termin ważności nie jest polem w bazie, tylko sumą daty i długości.
        # Filtr liczący wszystkim tak samo pomyliłby te dwa wiersze.
        zaproszenie(tenant, ile_dni_temu=3, dlugosc="1d")  # wygasło
        zaproszenie(tenant, ile_dni_temu=3, dlugosc="7d")  # jeszcze ważne

        dane = raport_zaproszen(timezone.now())

        assert ile_do_usuniecia(dane, "nie do użycia już dziś") == 1
        assert ile_nietykalnych(dane) == 1

    def test_swieze_wykorzystane_zaproszenie_nie_jest_stare(self, tenant):
        """
        Wykryte pierwszym raportem z produkcji, 17.09.2026.

        Zaproszenie wykorzystane dzień wcześniej trafiało do wszystkich progów,
        łącznie z „ponad 90 dni": warunek wykorzystania nie patrzył na wiek
        w ogóle. Raport pokazywał wtedy liczbę, której żadne usuwanie by nie
        powtórzyło - czyli dokładnie to, przed czym ten plik miał chronić.
        """
        zaproszenie(tenant, ile_dni_temu=1, dlugosc="7d", uzyte=1, miejsc=1)

        progi = dict(raport_zaproszen(timezone.now())["progi"])

        assert progi["nie do użycia już dziś"] == 1
        assert progi["j.w. i utworzone ponad 30 dni temu"] == 0
        assert progi["j.w. i utworzone ponad 90 dni temu"] == 0

    def test_stare_wykorzystane_zaproszenie_wchodzi_do_progow(self, tenant):
        zaproszenie(tenant, ile_dni_temu=120, dlugosc="7d", uzyte=1, miejsc=1)

        progi = dict(raport_zaproszen(timezone.now())["progi"])

        assert progi["j.w. i utworzone ponad 30 dni temu"] == 1
        assert progi["j.w. i utworzone ponad 90 dni temu"] == 1

    def test_niewyslane_powiadomienie_zostaje(self, user):
        teraz = timezone.now()
        PasswordNotification.objects.create(
            user=user, recipient="a@example.com", created_at=teraz - 200 * DZIEN
        )
        PasswordNotification.objects.create(
            user=user,
            recipient="b@example.com",
            created_at=teraz - 200 * DZIEN,
            status=PasswordNotification.Status.SENT,
        )

        dane = raport_powiadomien(teraz)

        assert ile_do_usuniecia(dane, "starsze niż 90 dni") == 1
        assert ile_nietykalnych(dane) == 1


class TestDziennika:
    def test_progi_dziela_wpisy_po_wieku(self):
        wpis_dziennika(400)
        wpis_dziennika(200)
        wpis_dziennika(10)

        progi = dict(raport_dziennika(timezone.now())["progi"])

        assert progi["starsze niż 3 mies."] == 2
        assert progi["starsze niż 6 mies."] == 2
        assert progi["starsze niż 12 mies."] == 1
        assert progi["starsze niż 24 mies."] == 0


def test_raport_niczego_nie_usuwa(user, tenant):
    # Cały sens tej komendy: dać liczby przed decyzją, nie zamiast niej.
    sesja(user, 3 * DZIEN)
    wpis_dziennika(400)
    zaproszenie(tenant, ile_dni_temu=100)
    przed = (
        LoginSession.objects.count(),
        WpisDziennika.objects.count(),
        InvitationToken.objects.count(),
    )

    call_command("raport_retencji")

    assert przed == (
        LoginSession.objects.count(),
        WpisDziennika.objects.count(),
        InvitationToken.objects.count(),
    )


def test_pusta_baza_nie_wywraca_raportu():
    # Nowe wdrożenie albo świeża baza próby: raport ma odpowiedzieć zerami,
    # a nie wyjątkiem o brakującej dacie najstarszego wiersza.
    CustomUser.objects.all().delete()

    call_command("raport_retencji")
