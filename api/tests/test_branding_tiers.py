"""
Trzy progi brandingu i wartości logiczne z formularza.

Cennik rozdziela trzy poziomy: Start reklamuje nas stopką, Grow pozwala ją
ukryć, Pro daje własną markę. Bez środkowego progu Grow nie różnił się od
Startu niczym poza limitem wiadomości, choć kosztuje ponad dwa razy więcej.

Przy okazji naprawiony błąd, który dotyczył już wdrożonego pola: panel wysyła
ustawienia jako multipart (w tym samym żądaniu lecą logo i awatar), więc
wartość logiczna przychodzi jako napis "true". Django uznaje wyłącznie "True"
i "1", a na "true" rzuca wyjątkiem — zapis kończył się błędem zamiast zapisać
ustawienie.
"""

import pytest
from rest_framework.test import APIClient

from accounts.plans import allows_hiding_branding, allows_white_label


def wlasciciel(user, tenant, plan):
    user.tenant = tenant
    user.role = "owner"
    user.save()
    subskrypcja = tenant.subscription
    subskrypcja.plan_type = plan
    subskrypcja.save()

    klient = APIClient()
    klient.force_authenticate(user=user)
    klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))
    return klient


class TestProgowWKatalogu:
    @pytest.mark.parametrize(
        "plan,ukrywanie,wlasna_marka",
        [
            ("start", False, False),
            ("grow", True, False),
            ("pro", True, True),
        ],
    )
    def test_uprawnienia_rosna_wraz_z_planem(self, plan, ukrywanie, wlasna_marka):
        assert allows_hiding_branding(plan) is ukrywanie
        assert allows_white_label(plan) is wlasna_marka


@pytest.mark.django_db
class TestBramkiUkrywaniaStopki:
    URL = "/api/widget-settings/mine/"

    def test_start_nie_ukryje_stopki(self, user, tenant, subscribtion):
        """Bez bramki klient Startu wyłączyłby ją zwykłym żądaniem PATCH."""
        klient = wlasciciel(user, tenant, "start")

        response = klient.patch(self.URL, {"widget_hide_branding": True}, format="json")

        assert response.status_code == 403
        tenant.refresh_from_db()
        assert tenant.widget_hide_branding is False

    def test_grow_ukryje_stopke(self, user, tenant, subscribtion):
        klient = wlasciciel(user, tenant, "grow")

        response = klient.patch(self.URL, {"widget_hide_branding": True}, format="json")

        assert response.status_code == 200
        tenant.refresh_from_db()
        assert tenant.widget_hide_branding is True

    def test_grow_nadal_bez_wlasnej_marki(self, user, tenant, subscribtion):
        """Środkowy próg to ukrycie stopki, nie pełna biała etykieta."""
        klient = wlasciciel(user, tenant, "grow")

        response = klient.patch(self.URL, {"branding_mode": "white_label"}, format="json")

        assert response.status_code == 403

    def test_wylaczenie_ukrycia_zawsze_dozwolone(self, user, tenant, subscribtion):
        """
        Po zejściu z planu klient musi móc cofnąć ustawienie, którego już mu
        nie wolno mieć — inaczej zostałby z nim na stałe, bez możliwości zmiany.
        """
        tenant.widget_hide_branding = True
        tenant.save()
        klient = wlasciciel(user, tenant, "start")

        response = klient.patch(self.URL, {"widget_hide_branding": False}, format="json")

        assert response.status_code == 200
        tenant.refresh_from_db()
        assert tenant.widget_hide_branding is False

    def test_widget_dostaje_informacje_o_stopce(self, tenant):
        tenant.widget_hide_branding = True
        tenant.save()

        dane = APIClient().get("/api/widget-settings/", HTTP_X_API_KEY=str(tenant.api_key)).json()

        assert dane["widget_hide_branding"] is True


@pytest.mark.django_db
class TestWartosciLogicznychZFormularza:
    """
    Sedno naprawionego błędu. Testy wysyłające JSON go nie łapały, bo tam
    wartość logiczna zostaje wartością logiczną — panel wysyła multipart.
    """

    URL = "/api/widget-settings/mine/"

    @pytest.mark.parametrize(
        "napis,oczekiwane",
        [
            ("true", True),
            ("false", False),
            ("True", True),
            ("False", False),
            ("1", True),
            ("0", False),
        ],
    )
    def test_zaczepka_zapisuje_sie_z_formularza(
        self, user, tenant, subscribtion, napis, oczekiwane
    ):
        klient = wlasciciel(user, tenant, "grow")

        response = klient.patch(self.URL, {"widget_proactive_enabled": napis}, format="multipart")

        assert response.status_code == 200
        tenant.refresh_from_db()
        assert tenant.widget_proactive_enabled is oczekiwane

    def test_ukrycie_stopki_zapisuje_sie_z_formularza(self, user, tenant, subscribtion):
        klient = wlasciciel(user, tenant, "grow")

        response = klient.patch(self.URL, {"widget_hide_branding": "true"}, format="multipart")

        assert response.status_code == 200
        tenant.refresh_from_db()
        assert tenant.widget_hide_branding is True

    def test_napis_false_nie_jest_prawda(self, user, tenant, subscribtion):
        """
        Zwykłe bool("false") daje True — gdyby konwersja poszła tą drogą,
        odznaczenie checkboxa włączałoby ustawienie zamiast je wyłączać.
        """
        tenant.widget_hide_branding = True
        tenant.save()
        klient = wlasciciel(user, tenant, "grow")

        klient.patch(self.URL, {"widget_hide_branding": "false"}, format="multipart")

        tenant.refresh_from_db()
        assert tenant.widget_hide_branding is False
