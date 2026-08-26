"""
Sesja oparta o ciasteczko HttpOnly.

Kategoria ryzyka: DOSTEP. Bledy w tej warstwie nie objawiaja sie bledem --
objawiaja sie tym, ze cos dziala mimo iz nie powinno. Wylogowanie, ktore
nie uniewaznia tokenu, wyglada identycznie jak takie, ktore uniewaznia.
Dlatego kazdy test sprawdza obie polowki: ze droga wlasciwa dziala ORAZ
ze droga niewlasciwa jest zamknieta.
"""
import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Tenant

NAZWA = settings.NAZWA_CIASTECZKA_ODSWIEZANIA
ZNACZNIK = settings.NAZWA_CIASTECZKA_SESJI


@pytest.fixture
def haslo():
    return "bardzo-tajne-haslo-123"


@pytest.fixture
def wlascicielka(django_user_model, haslo):
    tenant = Tenant.objects.create(name="Rowerownia Krakowska")
    return django_user_model.objects.create_user(
        username="wlascicielka@rowerownia.pl",
        email="wlascicielka@rowerownia.pl",
        password=haslo,
        tenant=tenant,
        role="owner",
    )


@pytest.fixture
def klient():
    return APIClient()


def zaloguj(klient, uzytkownik, haslo):
    return klient.post(
        reverse("login"),
        {"username": uzytkownik.username, "password": haslo},
        format="json",
    )


class TestLogowanie:
    def test_token_odswiezania_wraca_w_ciasteczku_httponly(self, klient, wlascicielka, haslo):
        odpowiedz = zaloguj(klient, wlascicielka, haslo)

        assert odpowiedz.status_code == 200
        ciasteczko = odpowiedz.cookies[NAZWA]
        assert ciasteczko.value
        # To jest cala istota zmiany: skrypt na stronie nie ma jak tego przeczytac.
        assert ciasteczko["httponly"] is True
        assert ciasteczko["samesite"] == "Lax"

    def test_token_dostepu_wraca_w_tresci(self, klient, wlascicielka, haslo):
        # Token dostepu MA byc widoczny dla JavaScriptu -- frontend trzyma go
        # w pamieci karty i dokleja do naglowka. Gdyby i on poszedl wylacznie
        # w ciasteczku, kazde zapytanie do API niosloby go automatycznie,
        # co otwiera CSRF na wszystkich koncowkach zapisujacych.
        odpowiedz = zaloguj(klient, wlascicielka, haslo)

        assert odpowiedz.data["access"]

    def test_zle_haslo_nie_ustawia_ciasteczka(self, klient, wlascicielka):
        odpowiedz = klient.post(
            reverse("login"),
            {"username": wlascicielka.username, "password": "nie-to-haslo"},
            format="json",
        )

        assert odpowiedz.status_code == 401
        assert NAZWA not in odpowiedz.cookies


class TestZnacznikSesji:
    """
    Znacznik pozwala serwerowi Next.js odmowic trasy PRZED renderem.
    Bez niego chroniona tresc miga na ekranie, zanim kod po stronie
    klienta zdazy przekierowac.
    """

    def test_logowanie_ustawia_znacznik_na_calej_domenie(self, klient, wlascicielka, haslo):
        odpowiedz = zaloguj(klient, wlascicielka, haslo)

        znacznik = odpowiedz.cookies[ZNACZNIK]
        # Sciezka "/" to caly sens tego ciasteczka: token ma sciezke
        # /api/accounts/, wiec pod panel w ogole nie dochodzi.
        assert znacznik["path"] == "/"
        assert znacznik["httponly"] is True

    def test_znacznik_nie_niesie_tokenu(self, klient, wlascicielka, haslo):
        # Gdyby cokolwiek z tokenu tu trafilo, zawezenie sciezki tego
        # drugiego ciasteczka byloby bez znaczenia.
        odpowiedz = zaloguj(klient, wlascicielka, haslo)

        token = odpowiedz.cookies[NAZWA].value
        assert odpowiedz.cookies[ZNACZNIK].value == "1"
        assert token not in odpowiedz.cookies[ZNACZNIK].value

    def test_wylogowanie_kasuje_oba_ciasteczka(self, klient, wlascicielka, haslo):
        # Znacznik zostawiony po wylogowaniu kazalby Next.js renderowac
        # panel, ktory natychmiast odbija sie od API -- uzytkownik widzi
        # migniecie panelu zamiast ekranu logowania.
        zaloguj(klient, wlascicielka, haslo)

        odpowiedz = klient.post(reverse("logout"))

        assert odpowiedz.cookies[NAZWA].value == ""
        assert odpowiedz.cookies[ZNACZNIK].value == ""


class TestOdswiezanie:
    def test_dziala_bez_podawania_tokenu_w_tresci(self, klient, wlascicielka, haslo):
        # Frontend nie ma czego wyslac -- token jest dla niego niewidoczny.
        zaloguj(klient, wlascicielka, haslo)

        odpowiedz = klient.post(reverse("token_refresh"))

        assert odpowiedz.status_code == 200
        assert odpowiedz.data["access"]

    def test_nowy_token_dostepu_naprawde_otwiera_api(self, klient, wlascicielka, haslo):
        # Sam fakt, ze koncowka zwrocila 200 i jakis napis, niczego nie dowodzi.
        zaloguj(klient, wlascicielka, haslo)
        nowy = klient.post(reverse("token_refresh")).data["access"]

        klient.credentials(HTTP_AUTHORIZATION=f"Bearer {nowy}")
        odpowiedz = klient.get(reverse("me"))

        assert odpowiedz.status_code == 200

    def test_rotacja_podmienia_ciasteczko(self, klient, wlascicielka, haslo):
        stary = zaloguj(klient, wlascicielka, haslo).cookies[NAZWA].value

        odpowiedz = klient.post(reverse("token_refresh"))

        assert odpowiedz.cookies[NAZWA].value != stary

    def test_zuzyty_token_przestaje_dzialac(self, klient, wlascicielka, haslo):
        # Bez tego rotacja jest tylko kosmetyka: stary token dzialalby dalej,
        # wiec kopia zdjeta przez napastnika otwieralaby panel przez dwa
        # tygodnie, a wlasciciel niczego by nie zauwazyl.
        stary = zaloguj(klient, wlascicielka, haslo).cookies[NAZWA].value
        klient.post(reverse("token_refresh"))

        klient.cookies[NAZWA] = stary
        odpowiedz = klient.post(reverse("token_refresh"))

        assert odpowiedz.status_code == 401

    def test_brak_ciasteczka_to_401_a_nie_400(self, klient):
        # Dla frontendu to ten sam przypadek co wygasla sesja i ma prowadzic
        # do ekranu logowania, a nie do komunikatu o bledzie formularza.
        odpowiedz = klient.post(reverse("token_refresh"))

        assert odpowiedz.status_code == 401

    def test_odrzucony_token_kasuje_ciasteczko(self, klient, wlascicielka, haslo):
        # Ciasteczko, ktorego juz nie da sie uzyc, tylko kaze przegladarce
        # probowac w kolko. Kasujemy je razem z odmowa.
        zaloguj(klient, wlascicielka, haslo)
        klient.cookies[NAZWA] = "to-nie-jest-zaden-token"

        odpowiedz = klient.post(reverse("token_refresh"))

        assert odpowiedz.status_code == 401
        assert odpowiedz.cookies[NAZWA].value == ""


class TestWylogowanie:
    def test_kasuje_ciasteczko(self, klient, wlascicielka, haslo):
        zaloguj(klient, wlascicielka, haslo)

        odpowiedz = klient.post(reverse("logout"))

        assert odpowiedz.status_code == 204
        assert odpowiedz.cookies[NAZWA].value == ""

    def test_uniewaznia_token_a_nie_tylko_chowa(self, klient, wlascicielka, haslo):
        # Najwazniejszy test w tym pliku. Samo skasowanie ciasteczka jest
        # gestem po stronie przegladarki -- token zdjety wczesniej z tego
        # urzadzenia otwieralby panel jeszcze przez dwa tygodnie.
        token = zaloguj(klient, wlascicielka, haslo).cookies[NAZWA].value
        klient.post(reverse("logout"))

        klient.cookies[NAZWA] = token
        odpowiedz = klient.post(reverse("token_refresh"))

        assert odpowiedz.status_code == 401

    def test_wylogowanie_bez_sesji_nie_wybucha(self, klient):
        # Kliknięcie "wyloguj" po wygasnieciu sesji ma po prostu zadzialac.
        odpowiedz = klient.post(reverse("logout"))

        assert odpowiedz.status_code == 204
