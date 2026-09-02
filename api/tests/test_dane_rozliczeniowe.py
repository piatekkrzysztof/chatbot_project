"""
Odczyt i zmiana danych do faktury.

Kategoria ryzyka: PIENIĄDZE i IZOLACJA. Te dane decydują o tym, na kogo idzie
faktura i z kim zawarta jest umowa - pomyłka tutaj kosztuje korektę dokumentu,
a wyciek między najemcami pokazuje jednej firmie adres i NIP drugiej.
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import DaneRozliczeniowe, Tenant

URL = "/api/accounts/dane-rozliczeniowe/"


@pytest.fixture
def firma(db):
    return Tenant.objects.create(name="Rowerownia", owner_email="szef@rowerownia.pl")


@pytest.fixture
def wlascicielka(db, django_user_model, firma):
    return django_user_model.objects.create_user(
        username="szef@rowerownia.pl",
        email="szef@rowerownia.pl",
        password="tajne-haslo-2026",
        tenant=firma,
        role="owner",
    )


@pytest.fixture
def klient(wlascicielka, firma):
    api = APIClient()
    api.force_authenticate(user=wlascicielka)
    api.credentials(HTTP_X_API_KEY=str(firma.api_key))
    return api


@pytest.fixture
def dane(firma):
    return DaneRozliczeniowe.objects.create(
        tenant=firma,
        nazwa="Rowerownia Krakowska Anna Nowak",
        nip="5260250274",
        ulica="Krakowska 12",
        kod_pocztowy="31-000",
        miasto="Kraków",
    )


@pytest.mark.django_db
class TestOdczytu:
    def test_wlascicielka_widzi_swoje_dane(self, klient, dane):
        odpowiedz = klient.get(URL)

        assert odpowiedz.status_code == 200
        assert odpowiedz.data["nip"] == "5260250274"
        assert odpowiedz.data["miasto"] == "Kraków"

    def test_konto_bez_danych_dostaje_pusty_formularz_a_nie_bledu(self, klient, firma):
        """
        Konta założone przed wprowadzeniem tych pól nie mają jeszcze wiersza.
        404 znaczyłoby dla panelu "coś się zepsuło", a klient ma po prostu
        zobaczyć formularz do wypełnienia.
        """
        odpowiedz = klient.get(URL)

        assert odpowiedz.status_code == 200
        assert odpowiedz.data["nazwa"] == "Rowerownia"
        assert odpowiedz.data["ulica"] == ""


@pytest.mark.django_db
class TestZmiany:
    def test_zmiana_adresu_zapisuje_sie(self, klient, dane):
        odpowiedz = klient.patch(URL, {"ulica": "Nowa 5", "miasto": "Wrocław"}, format="json")

        assert odpowiedz.status_code == 200
        dane.refresh_from_db()
        assert dane.ulica == "Nowa 5"
        assert dane.miasto == "Wrocław"

    def test_zly_nip_jest_odrzucany_tak_samo_jak_przy_rejestracji(self, klient, dane):
        """
        Najważniejszy test w tym pliku.

        Gdyby edycja sprawdzała mniej niż rejestracja, wystarczyłoby wejść
        w ustawienia, żeby ominąć regułę - czyli obowiązywałaby wyłącznie przy
        pierwszym wpisaniu, a to najmniej istotny moment. Adres i NIP zmieniają
        się później, nie przy zakładaniu konta.
        """
        odpowiedz = klient.patch(URL, {"nip": "5260250247"}, format="json")

        assert odpowiedz.status_code == 400
        dane.refresh_from_db()
        assert dane.nip == "5260250274"

    def test_nip_zapisuje_sie_znormalizowany(self, klient, dane):
        klient.patch(URL, {"nip": "526-025-02-74"}, format="json")

        dane.refresh_from_db()
        assert dane.nip == "5260250274"

    def test_mozna_usunac_nip(self, klient, dane):
        # Firma bywa wykreślona z rejestru VAT albo klient przechodzi na
        # zakup prywatny - puste pole musi być dozwolone.
        odpowiedz = klient.patch(URL, {"nip": ""}, format="json")

        assert odpowiedz.status_code == 200
        dane.refresh_from_db()
        assert dane.nip == ""


@pytest.mark.django_db
class TestDostepu:
    def test_pracownik_nie_widzi_danych_rozliczeniowych(self, klient, wlascicielka, dane):
        # Faktura i umowa to nie jest ustawienie robocze. Pracownik zmieniający
        # adres na fakturze byłby najprostszą drogą do wystawienia dokumentu
        # na kogoś innego.
        wlascicielka.role = "employee"
        wlascicielka.save()

        assert klient.get(URL).status_code == 403
        assert klient.patch(URL, {"miasto": "Gdańsk"}, format="json").status_code == 403

    def test_dane_innej_firmy_sa_niewidoczne(self, klient, dane, db, django_user_model):
        obca_firma = Tenant.objects.create(name="Obca firma")
        DaneRozliczeniowe.objects.create(
            tenant=obca_firma,
            nazwa="Obca firma sp. z o.o.",
            nip="",
            ulica="Tajna 1",
            kod_pocztowy="00-001",
            miasto="Warszawa",
        )

        odpowiedz = klient.get(URL)

        assert odpowiedz.data["nazwa"] == "Rowerownia Krakowska Anna Nowak"
        assert "Tajna" not in str(odpowiedz.data)
