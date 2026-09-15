"""
Pierwsze kroki na pulpicie.

Kategoria ryzyka: WDROŻENIE KLIENTA. Nowa firma po rejestracji widziała pulpit
z zerami i ostrzeżenie o pustej wiedzy - i nic poza tym. Nie dowiadywała się,
że bot bez wklejonego kodu nie pojawi się na jej stronie, że zapytania z czatu
trafiają na adres do powiadomień ani że widget pokazuje link do polityki
prywatności. Każdy krok liczy się z danych, które już są w bazie, więc nie da
się go odhaczyć bez wykonania.
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import WidgetDomain
from chat.models import Conversation
from chat.zapytania import ZRODLO_IMPORTU, ZRODLO_TESTOWE

KROKI = {
    "wiedza",
    "rozmowa_testowa",
    "widget_na_stronie",
    "adres_powiadomien",
    "polityka_prywatnosci",
}


def pierwsze_kroki(user, tenant):
    user.tenant = tenant
    user.role = "owner"
    user.save()
    klient = APIClient()
    klient.force_authenticate(user=user)
    odpowiedz = klient.get("/api/analytics/", HTTP_X_API_KEY=str(tenant.api_key))
    assert odpowiedz.status_code == 200
    return odpowiedz.json()["pierwsze_kroki"]


@pytest.fixture
def nowa_firma(tenant, subscribtion):
    tenant.owner_email = ""
    tenant.privacy_policy_url = ""
    tenant.gpt_prompt = ""
    tenant.save()
    return tenant


@pytest.mark.django_db
class TestPierwszychKrokow:
    def test_swieza_firma_nie_ma_zadnego_kroku(self, user, nowa_firma):
        assert pierwsze_kroki(user, nowa_firma) == dict.fromkeys(KROKI, False)

    def test_opis_firmy_zamyka_krok_wiedzy(self, user, nowa_firma):
        nowa_firma.gpt_prompt = "Serwis i sprzedaż rowerów w Krakowie."
        nowa_firma.save()

        assert pierwsze_kroki(user, nowa_firma)["wiedza"] is True

    def test_rozmowa_testowa_z_panelu(self, user, nowa_firma):
        Conversation.objects.create(
            tenant=nowa_firma, user_identifier=f"panel:{user.id}", source=ZRODLO_TESTOWE
        )

        assert pierwsze_kroki(user, nowa_firma)["rozmowa_testowa"] is True

    def test_rozmowa_odwiedzajacego_tez_zamyka_krok_testu(self, user, nowa_firma):
        # Gdy piszą już prawdziwi klienci, namawianie do rozmowy testowej jest
        # szumem - krok ma sprawdzić, czy bot odpowiada, a to już wiadomo.
        Conversation.objects.create(tenant=nowa_firma, user_identifier="a1b2", source="widget")

        assert pierwsze_kroki(user, nowa_firma)["rozmowa_testowa"] is True

    def test_historia_wgrana_z_csv_nie_jest_rozmowa_testowa(self, user, nowa_firma):
        # Import przenosi stare rozmowy z innego narzędzia. Nie mówi nic o tym,
        # czy nasz bot odpowiada na pytania tej firmy.
        Conversation.objects.create(
            tenant=nowa_firma, user_identifier=ZRODLO_IMPORTU, source=ZRODLO_IMPORTU
        )

        assert pierwsze_kroki(user, nowa_firma)["rozmowa_testowa"] is False

    def test_widget_na_stronie_po_wykryciu_witryny(self, user, nowa_firma):
        WidgetDomain.objects.create(tenant=nowa_firma, host="rowerownia.pl")

        assert pierwsze_kroki(user, nowa_firma)["widget_na_stronie"] is True

    def test_adres_lokalny_nie_jest_instalacja_na_stronie(self, user, nowa_firma):
        # Rejestracja domen dziś je pomija, ale starsze wpisy mogły zostać.
        # Widget otwarty na własnym komputerze nie jest na stronie klienta.
        for host in ("localhost", "null", "192.168.1.10"):
            WidgetDomain.objects.create(tenant=nowa_firma, host=host)

        assert pierwsze_kroki(user, nowa_firma)["widget_na_stronie"] is False

    def test_adres_powiadomien(self, user, nowa_firma):
        nowa_firma.owner_email = "   "
        nowa_firma.save()
        assert pierwsze_kroki(user, nowa_firma)["adres_powiadomien"] is False

        nowa_firma.owner_email = "biuro@rowerownia.pl"
        nowa_firma.save()
        assert pierwsze_kroki(user, nowa_firma)["adres_powiadomien"] is True

    def test_link_do_polityki_prywatnosci(self, user, nowa_firma):
        nowa_firma.privacy_policy_url = "https://rowerownia.pl/prywatnosc"
        nowa_firma.save()

        assert pierwsze_kroki(user, nowa_firma)["polityka_prywatnosci"] is True

    def test_kroki_innej_firmy_sie_nie_licza(self, user, nowa_firma):
        from .factories import TenantFactory

        obca = TenantFactory()
        WidgetDomain.objects.create(tenant=obca, host="obca-firma.pl")
        Conversation.objects.create(tenant=obca, user_identifier="x", source=ZRODLO_TESTOWE)
        Conversation.objects.create(tenant=obca, user_identifier="y", source="widget")

        kroki = pierwsze_kroki(user, nowa_firma)

        assert kroki["widget_na_stronie"] is False
        assert kroki["rozmowa_testowa"] is False
