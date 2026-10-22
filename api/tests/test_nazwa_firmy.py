"""
Nazwa firmy bez znaków sterujących (2.32.13).

Nazwa trafia do tematu każdego maila do właściciela: zapytanie z czatu, nowa
rozmowa, raport luk, limity. Django odrzuca temat ze znakiem nowej linii
(`BadHeaderError`), więc nazwa zapisana z `\\n` po cichu wyłączała wszystkie
powiadomienia tej firmy - każde kończyło się błędem przy wysyłce (audyt
2026-10, P15). Do wstrzyknięcia nagłówka nie dochodziło, bo Django odrzuca całą
wiadomość, ale skutek dla klienta był ten sam co awaria poczty.
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import CustomUser, Tenant
from api.session_tokens import SessionRefreshToken
from api.tests.signup_helpers import complete_registration

# Znak na samym końcu i tak zdejmuje przycinanie nazwy - liczy się ten w środku.
ZLE_NAZWY = ["Firma\nBcc: ktos@example.com", "Fir\rma", "Firma\tKrakow", "Fir\x00ma"]


@pytest.fixture
def wlasciciel(db):
    firma = Tenant.objects.create(name="Firma", owner_email="w@example.com")
    konto = CustomUser.objects.create_user(
        username="nazwa", email="nazwa@example.com", tenant=firma, role="owner"
    )
    klient = APIClient()
    klient.credentials(
        HTTP_AUTHORIZATION=f"Bearer {SessionRefreshToken.for_user(konto).access_token}"
    )
    return firma, klient


@pytest.mark.django_db
class TestUstawieniaFirmy:
    @pytest.mark.parametrize("nazwa", ZLE_NAZWY)
    def test_znak_sterujacy_odrzucony(self, wlasciciel, nazwa):
        firma, klient = wlasciciel

        odpowiedz = klient.patch("/api/accounts/firma/", {"name": nazwa}, format="json")

        assert odpowiedz.status_code == 400
        assert "name" in odpowiedz.json()
        firma.refresh_from_db()
        assert firma.name == "Firma"

    def test_zwykla_nazwa_z_polskimi_literami_przechodzi(self, wlasciciel):
        firma, klient = wlasciciel

        odpowiedz = klient.patch(
            "/api/accounts/firma/", {"name": "Cukiernia „Łączka” sp. z o.o."}, format="json"
        )

        assert odpowiedz.status_code == 200
        firma.refresh_from_db()
        assert firma.name == "Cukiernia „Łączka” sp. z o.o."


@pytest.mark.django_db
class TestRejestracja:
    PAYLOAD = {
        "imie": "Anna",
        "nazwisko": "Nowak",
        "email": "anna@example.com",
        "password": "SuperHaslo123",
        "ulica": "Krakowska 12",
        "kod_pocztowy": "31-000",
        "miasto": "Krakow",
    }

    @pytest.mark.parametrize("nazwa", ZLE_NAZWY)
    def test_znak_sterujacy_odrzucony_przy_rejestracji(self, nazwa):
        klient = APIClient(HTTP_ORIGIN="https://panel.example.test")

        odpowiedz = klient.post(
            "/api/accounts/register/", {**self.PAYLOAD, "company_name": nazwa}, format="json"
        )

        assert odpowiedz.status_code == 400
        assert "company_name" in odpowiedz.json()

    def test_zwykla_nazwa_rejestruje_sie(self):
        klient = APIClient(HTTP_ORIGIN="https://panel.example.test")
        odpowiedz = klient.post(
            "/api/accounts/register/", {**self.PAYLOAD, "company_name": "Łączka"}, format="json"
        )

        assert complete_registration(odpowiedz, self.PAYLOAD["password"]).status_code == 201
        assert Tenant.objects.filter(name="Łączka").exists()
