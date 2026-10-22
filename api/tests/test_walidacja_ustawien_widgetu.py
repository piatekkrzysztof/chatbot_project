"""
Zapis ustawień widgetu sprawdza wartości, zanim trafią do bazy (2.32.10).

Do 2.32.9 `PATCH /api/widget-settings/mine/` przepisywał pola wprost z żądania.
Liczba sekund jako tekst albo za długa pozycja kończyły się błędem 500, a pozycja
„srodek", tryb brandingu „cokolwiek" czy kolor „red;}x{" zapisywały się i szły
do widgetu na stronie klienta (audyt 2026-10, P12). Teraz zła wartość to 400
z nazwą pola, a zapis jest w całości albo wcale.
"""

from datetime import date, timedelta

import pytest
from rest_framework.test import APIClient

from accounts.models import CustomUser, Subscription, Tenant
from api.session_tokens import SessionRefreshToken

ADRES = "/api/widget-settings/mine/"


@pytest.fixture
def firma(db):
    tenant = Tenant.objects.create(name="Ustawienia")
    Subscription.objects.create(
        tenant=tenant,
        plan_type="pro",
        is_active=True,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=30),
    )
    return tenant


@pytest.fixture
def klient(firma):
    wlasciciel = CustomUser.objects.create_user(
        username="ustawienia", email="u@example.com", tenant=firma, role="owner"
    )
    klient = APIClient(raise_request_exception=False)
    klient.credentials(
        HTTP_AUTHORIZATION=f"Bearer {SessionRefreshToken.for_user(wlasciciel).access_token}"
    )
    return klient


ZLE_WARTOSCI = [
    {"widget_proactive_delay_seconds": "abc"},
    {"widget_proactive_delay_seconds": -1},
    {"widget_position": "srodek"},
    {"widget_position": "x" * 30},
    {"widget_color": "red;}x{"},
    {"widget_color": "#" + "0" * 25},
    {"branding_mode": "cokolwiek"},
    {"branding_mode": "white_label "},
    {"widget_language_mode": "losowo"},
    {"widget_default_language": "xx"},
    {"widget_languages": "pl,xx"},
    {"widget_title": "x" * 101},
    {"widget_footer_text": "x" * 101},
    {"widget_footer_text": None},
]


@pytest.mark.django_db
class TestZleWartosci:
    @pytest.mark.parametrize("dane", ZLE_WARTOSCI, ids=lambda d: next(iter(d)))
    def test_zla_wartosc_daje_400_i_nie_zmienia_niczego(self, firma, klient, dane):
        przed = Tenant.objects.filter(pk=firma.pk).values().get()

        odpowiedz = klient.patch(ADRES, dane, format="json")

        assert odpowiedz.status_code == 400
        assert next(iter(dane)) in odpowiedz.json()
        assert Tenant.objects.filter(pk=firma.pk).values().get() == przed

    def test_jedna_zla_wartosc_wstrzymuje_caly_zapis(self, firma, klient):
        odpowiedz = klient.patch(
            ADRES, {"widget_title": "Nowy tytuł", "widget_position": "srodek"}, format="json"
        )

        assert odpowiedz.status_code == 400
        firma.refresh_from_db()
        assert firma.widget_title != "Nowy tytuł"


@pytest.mark.django_db
class TestDobreWartosci:
    def test_wartosci_z_panelu_zapisuja_sie(self, firma, klient):
        odpowiedz = klient.patch(
            ADRES,
            {
                "widget_position": "left",
                "widget_color": "#1A73E8",
                "widget_title": "Cukiernia",
                "branding_mode": "white_label",
                "widget_footer_text": "",
                "widget_welcome_message": "Dzień dobry!",
                "widget_suggested_questions": "Godziny?\nCennik?",
                "widget_languages": "pl,de",
                "widget_language_mode": "fixed",
                "widget_default_language": "de",
                "widget_proactive_delay_seconds": 15,
            },
            format="json",
        )

        assert odpowiedz.status_code == 200, odpowiedz.json()
        firma.refresh_from_db()
        assert (firma.widget_position, firma.widget_color, firma.branding_mode) == (
            "left",
            "#1A73E8",
            "white_label",
        )
        assert (firma.widget_languages, firma.widget_default_language) == ("pl,de", "de")
        assert firma.widget_proactive_delay_seconds == 15

    @pytest.mark.parametrize("kolor", ["#fff", "#00ff00", "#00ff0080"])
    def test_kolory_szesnastkowe(self, firma, klient, kolor):
        assert klient.patch(ADRES, {"widget_color": kolor}, format="json").status_code == 200

    def test_jezyki_jako_lista_zapisuja_sie_jak_z_panelu(self, firma, klient):
        odpowiedz = klient.patch(ADRES, {"widget_languages": ["pl", "en"]}, format="json")

        assert odpowiedz.status_code == 200
        firma.refresh_from_db()
        assert firma.widget_languages == "pl,en"
        assert odpowiedz.json()["widget_languages"] == ["pl", "en"]

    def test_formularz_multipart_z_liczba_jako_tekstem(self, firma, klient):
        odpowiedz = klient.patch(
            ADRES,
            {"widget_proactive_delay_seconds": "45", "widget_title": "Tort"},
            format="multipart",
        )

        assert odpowiedz.status_code == 200
        firma.refresh_from_db()
        assert (firma.widget_proactive_delay_seconds, firma.widget_title) == (45, "Tort")

    def test_spacje_w_tekstach_zostaja(self, firma, klient):
        """Zapis jak dotąd: walidacja nie przycina tekstów, które wpisał klient."""
        klient.patch(ADRES, {"widget_welcome_message": "  Witaj!  "}, format="json")

        firma.refresh_from_db()
        assert firma.widget_welcome_message == "  Witaj!  "
