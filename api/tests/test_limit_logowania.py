"""
Limit prób logowania.

Kategoria ryzyka: DOSTĘP. Do 27 sierpnia 2026 końcówka logowania nie miała
żadnego limitu. Domyślne throttle'e tego projektu opierają się na
`request.tenant` albo `request.subscription`, a logowanie jest wyłączone
z `TenantMiddleware` - więc ich `get_cache_key` zwracał pusto i limit nie
obowiązywał. Hasła można było zgadywać bez ograniczeń, w tempie sieci.

Dwie warstwy, bo każda łapie co innego, i obie mają tu swoje testy:
po adresie - jednego napastnika, po koncie - rozproszone zgadywanie z wielu
adresów, które limit adresowy omija w całości.
"""

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Tenant

HASLO = "prawidlowe-haslo-2026"


@pytest.fixture(autouse=True)
def czysty_licznik():
    """
    Throttle trzyma liczniki w pamięci podręcznej, więc bez czyszczenia
    wynik testu zależy od tego, co robiły poprzednie - a to wygląda na błąd
    losowy i zjada wieczór.
    """
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def wlascicielka(django_user_model):
    firma = Tenant.objects.create(name="Rowerownia Krakowska")
    return django_user_model.objects.create_user(
        username="szef@rowerownia.pl",
        email="szef@rowerownia.pl",
        password=HASLO,
        tenant=firma,
        role="owner",
    )


def sprobuj(klient, login, haslo, adres="203.0.113.7"):
    return klient.post(
        reverse("login"),
        {"username": login, "password": haslo},
        format="json",
        REMOTE_ADDR=adres,
    )


@pytest.mark.django_db
class TestLimituPoAdresie:
    def test_zgadywanie_z_jednego_adresu_zostaje_zatrzymane(self, wlascicielka):
        klient = APIClient()

        odpowiedzi = [sprobuj(klient, "szef@rowerownia.pl", "zle") for _ in range(12)]
        kody = [odpowiedz.status_code for odpowiedz in odpowiedzi]

        assert 429 in kody, "logowanie nadal przyjmuje nieograniczona liczbe prob"
        # Pierwsze próby muszą przejść normalnie - limit ma zatrzymywać
        # maszynę, a nie człowieka, który raz pomylił hasło.
        assert kody[0] == 401

    def test_inny_adres_nie_dziedziczy_blokady(self, wlascicielka):
        # Limit adresowy nie może odcinać osób postronnych: jeden zablokowany
        # napastnik nie ma prawa uniemożliwić logowania całej reszcie.
        klient = APIClient()
        for _ in range(12):
            sprobuj(klient, "ktos@innego.pl", "zle", adres="203.0.113.7")

        odpowiedz = sprobuj(klient, "szef@rowerownia.pl", HASLO, adres="198.51.100.4")

        assert odpowiedz.status_code == 200


@pytest.mark.django_db
class TestLimituPoKoncie:
    def test_zgadywanie_z_wielu_adresow_tez_zostaje_zatrzymane(self, wlascicielka):
        """
        Najważniejszy test w tym pliku.

        Sam limit po adresie wygląda na wystarczający, dopóki nie zauważy się,
        że rozproszenie prób po wielu adresach jest dziś tanie. Ten test
        przechodziłby bez drugiej warstwy tylko wtedy, gdyby wszystkie próby
        szły z jednego miejsca - a nie idą.
        """
        klient = APIClient()

        kody = [
            sprobuj(klient, "szef@rowerownia.pl", "zle", adres=f"198.51.100.{numer}").status_code
            for numer in range(1, 10)
        ]

        assert 429 in kody, "konto mozna zgadywac w nieskonczonosc z roznych adresow"

    def test_inne_konto_nie_dziedziczy_blokady(self, wlascicielka, django_user_model):
        # Blokada jednego konta nie może zamykać drogi pozostałym - inaczej
        # wystarczyłoby atakować jedno konto, żeby wyłączyć panel wszystkim.
        firma = Tenant.objects.create(name="Inna firma")
        django_user_model.objects.create_user(
            username="ktos@innej.pl",
            email="ktos@innej.pl",
            password=HASLO,
            tenant=firma,
            role="owner",
        )
        klient = APIClient()
        for numer in range(1, 10):
            sprobuj(klient, "szef@rowerownia.pl", "zle", adres=f"198.51.100.{numer}")

        odpowiedz = sprobuj(klient, "ktos@innej.pl", HASLO, adres="192.0.2.50")

        assert odpowiedz.status_code == 200


@pytest.mark.django_db
class TestCoWidziAtakujacy:
    def test_odmowa_nie_zdradza_czy_konto_istnieje(self, wlascicielka):
        # Różnica w odpowiedzi między kontem istniejącym a nieistniejącym
        # zamienia logowanie w narzędzie do sprawdzania, kto jest klientem.
        klient = APIClient()

        istniejace = sprobuj(klient, "szef@rowerownia.pl", "zle", adres="192.0.2.1")
        nieistniejace = sprobuj(klient, "nikt@nigdzie.pl", "zle", adres="192.0.2.2")

        assert istniejace.status_code == nieistniejace.status_code
        assert istniejace.data == nieistniejace.data


@pytest.mark.django_db
class TestNormalnejPracy:
    def test_poprawne_haslo_dziala_i_nie_zuzywa_limitu_pod_szczytem(self, wlascicielka):
        # Limit ma nie przeszkadzać w normalnym użyciu: kilka logowań pod rząd
        # zdarza się przy pracy na dwóch przeglądarkach albo po wylogowaniu.
        klient = APIClient()

        kody = [sprobuj(klient, "szef@rowerownia.pl", HASLO).status_code for _ in range(4)]

        assert kody == [200, 200, 200, 200]
