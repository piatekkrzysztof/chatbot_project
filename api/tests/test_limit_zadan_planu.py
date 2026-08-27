"""
Limit żądań na minutę wg planu.

Cennik obiecuje 60, 150 albo 500 żądań na minutę. Mechanizm istniał i działał
poprawnie — ale tylko na trzech ścieżkach czatu, bo tylko tam
SubscriptionMiddleware ustawiał request.subscription. Na całej reszcie panelu
throttle nie widział subskrypcji, brał plan "free" i klient planu Pro chodził
po swoim panelu na stawce darmowej.

Testujemy dwie rzeczy: że stawka odpowiada planowi bez pomocy middleware
oraz że po jej przekroczeniu żądanie faktycznie dostaje 429. Sam fakt
poprawnego wyliczenia liczby nic nie znaczy, jeśli nie dochodzi do odrzucenia.
"""

from datetime import date, timedelta

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.models import CustomUser, Subscription, Tenant
from accounts.plans import rate_for
from api.throttles import APIKeyRateThrottle, SubscriptionRateThrottle


@pytest.fixture(autouse=True)
def czysty_licznik():
    """Throttling trzyma liczniki w cache — bez czyszczenia testy zlewają się."""
    cache.clear()
    yield
    cache.clear()


def firma_z_planem(plan, nazwa="Firma"):
    tenant = Tenant.objects.create(name=nazwa)
    # start_date i end_date są wymagane przez model — subskrypcja bez dat
    # nie istnieje w tym systemie, więc test nie może jej udawać.
    dzis = date.today()
    Subscription.objects.create(
        tenant=tenant,
        plan_type=plan,
        is_active=True,
        start_date=dzis - timedelta(days=1),
        end_date=dzis + timedelta(days=30),
    )
    return tenant


def zaloguj(tenant):
    user = CustomUser.objects.create_user(
        username=f"wlasciciel{tenant.pk}@example.com",
        email=f"wlasciciel{tenant.pk}@example.com",
        password="tajne123",
        tenant=tenant,
        role="owner",
    )
    klient = APIClient()
    klient.force_authenticate(user=user)
    klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))
    return klient


class ZadanieBezMiddleware:
    """Żądanie takie, jakie widzi throttle poza ścieżkami czatu: tenant jest
    (ustawia go TenantMiddleware), subskrypcji nie ma."""

    def __init__(self, tenant):
        self.tenant = tenant
        self.headers = {}


@pytest.mark.django_db
class TestStawkiZPlanu:
    @pytest.mark.parametrize(
        "plan,oczekiwana",
        [
            ("start", "60/min"),
            ("grow", "150/min"),
            ("pro", "500/min"),
        ],
    )
    def test_czat_dostaje_stawke_swojego_planu(self, plan, oczekiwana):
        throttle = APIKeyRateThrottle()
        throttle.request = ZadanieBezMiddleware(firma_z_planem(plan))
        assert throttle.get_rate() == oczekiwana
        assert throttle.get_rate() == rate_for(plan)

    @pytest.mark.parametrize(
        "plan,na_minute",
        [
            ("start", 600),
            ("grow", 1500),
            ("pro", 5000),
        ],
    )
    def test_panel_tez_dostaje_stawke_planu_bez_middleware(self, plan, na_minute):
        """Sedno poprawki. Wcześniej bez middleware wychodziło 300/min
        niezależnie od planu, bo throttle nie widział subskrypcji."""
        throttle = SubscriptionRateThrottle()
        throttle.request = ZadanieBezMiddleware(firma_z_planem(plan))
        assert throttle.get_rate() == f"{na_minute}/min"

    def test_bez_subskrypcji_zostaje_stawka_darmowa(self):
        """Konto bez aktywnej subskrypcji nie może dostać limitu planu
        tylko dlatego, że istnieje."""
        throttle = APIKeyRateThrottle()
        throttle.request = ZadanieBezMiddleware(Tenant.objects.create(name="Bez planu"))
        assert throttle.get_rate() == rate_for("free")

    def test_wygasla_subskrypcja_nie_daje_limitu_planu(self):
        tenant = Tenant.objects.create(name="Wygasła")
        dzis = date.today()
        Subscription.objects.create(
            tenant=tenant,
            plan_type="pro",
            is_active=False,
            start_date=dzis - timedelta(days=60),
            end_date=dzis - timedelta(days=30),
        )
        throttle = APIKeyRateThrottle()
        throttle.request = ZadanieBezMiddleware(tenant)
        assert throttle.get_rate() == rate_for("free")

    def test_subskrypcja_liczona_raz_na_zadanie(self):
        """Wynik ląduje na żądaniu, więc drugi throttle w łańcuchu nie robi
        tego samego zapytania po raz kolejny."""
        zadanie = ZadanieBezMiddleware(firma_z_planem("grow"))
        pierwszy = APIKeyRateThrottle()
        pierwszy.request = zadanie
        pierwszy.get_rate()

        assert getattr(zadanie, "subscription", None) is not None
        drugi = SubscriptionRateThrottle()
        drugi.request = zadanie
        assert drugi.get_rate() == "1500/min"


@pytest.mark.django_db
class TestRealnegoOdrzucenia:
    def test_po_przekroczeniu_limitu_leci_429(self, settings):
        """Wyliczona stawka jest bez znaczenia, jeśli nadmiarowe żądanie
        i tak przechodzi. Zaniżamy limit planu Start do dwóch na minutę
        i sprawdzamy, że trzecie żądanie zostaje odrzucone."""
        settings.REST_FRAMEWORK = {
            **settings.REST_FRAMEWORK,
            "DEFAULT_THROTTLE_RATES": {
                **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
                "subscription": "2/min",
            },
        }
        tenant = firma_z_planem("start")
        klient = zaloguj(tenant)

        class DwaNaMinute(SubscriptionRateThrottle):
            def get_plan_rate(self, plan):
                return "2/min"

        from api.views.documents import DocumentsViewSet

        pierwotne = DocumentsViewSet.throttle_classes
        DocumentsViewSet.throttle_classes = [DwaNaMinute]
        try:
            kody = [klient.get("/api/documents/").status_code for _ in range(3)]
        finally:
            DocumentsViewSet.throttle_classes = pierwotne

        assert kody[:2] == [200, 200], f"pierwsze dwa miały przejść: {kody}"
        assert kody[2] == 429, f"trzecie miało zostać odrzucone: {kody}"
