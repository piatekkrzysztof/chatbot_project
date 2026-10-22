"""
Limit prób logowania przy treści, która nie jest zwykłym formularzem (2.32.9).

Limit na konto czytał `request.data.get("username").strip()` i zakładał, że
treść to słownik, a nazwa - tekst. Liczba w polu nazwy albo lista zamiast
obiektu kończyły się błędem 500 i zdarzeniem w Sentry zamiast odpowiedzią 400
(audyt 2026-10, P11).

Poprawka nie może przy okazji otworzyć obejścia: formularz logowania zamienia
liczbę 123 na tekst "123", więc gdyby nietekstowa nazwa po prostu omijała
limit, wystarczyłoby wysyłać numeryczną nazwę konta jako liczbę.
"""

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Tenant

ORIGIN = "https://panel.example.test"


@pytest.fixture(autouse=True)
def czysty_licznik():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def konto_z_numerem(django_user_model):
    firma = Tenant.objects.create(name="Numery")
    return django_user_model.objects.create_user(
        username="123", email="numer@example.com", password="haslo-2026-x", tenant=firma
    )


def zaloguj(cialo, adres):
    klient = APIClient(HTTP_ORIGIN=ORIGIN, raise_request_exception=False)
    return klient.post(reverse("login"), cialo, format="json", REMOTE_ADDR=adres)


@pytest.mark.django_db
class TestTrescLogowania:
    @pytest.mark.parametrize(
        ("cialo", "kod"),
        [
            # Liczbę formularz przyjmuje jako tekst "123" - takiego konta nie ma.
            ({"username": 123, "password": "x"}, 401),
            ({"username": {"a": 1}, "password": "x"}, 400),
            ({"username": ["a"], "password": "x"}, 400),
            ({"username": None, "password": "x"}, 400),
            ({"username": True, "password": "x"}, 400),
            (["x"], 400),
            ("x", 400),
        ],
    )
    def test_nietypowa_tresc_daje_odmowe_a_nie_500(self, cialo, kod):
        assert zaloguj(cialo, "203.0.113.20").status_code == kod

    def test_nazwa_jako_liczba_liczy_sie_do_limitu_tego_samego_konta(self, konto_z_numerem):
        """Pięć prób tekstem "123" z różnych adresów, szósta liczbą 123 - też zatrzymana."""
        for numer in range(5):
            odpowiedz = zaloguj({"username": "123", "password": "zle"}, f"198.51.100.{numer}")
            assert odpowiedz.status_code == 401

        szosta = zaloguj({"username": 123, "password": "zle"}, "198.51.100.99")

        assert szosta.status_code == 429

    def test_tresc_odrzucona_przez_formularz_nie_zuzywa_limitu_konta(self, django_user_model):
        """Pięć prób z `True` w nazwie nie może zablokować konta o nazwie "true"."""
        firma = Tenant.objects.create(name="Prawda")
        django_user_model.objects.create_user(
            username="true", email="true@example.com", password="haslo-2026-x", tenant=firma
        )
        for numer in range(5):
            odrzucona = zaloguj({"username": True, "password": "zle"}, f"198.51.100.{numer}")
            assert odrzucona.status_code == 400

        prawdziwa = zaloguj({"username": "true", "password": "haslo-2026-x"}, "198.51.100.50")

        assert prawdziwa.status_code == 200

    def test_wielkosc_liter_nie_daje_osobnego_licznika(self, django_user_model):
        firma = Tenant.objects.create(name="Litery")
        django_user_model.objects.create_user(
            username="szef@litery.pl", email="szef@litery.pl", password="haslo-2026-x", tenant=firma
        )
        for numer in range(5):
            zaloguj({"username": "szef@litery.pl", "password": "zle"}, f"198.51.100.{numer}")

        szosta = zaloguj({"username": "SZEF@Litery.pl", "password": "zle"}, "198.51.100.77")

        assert szosta.status_code == 429
