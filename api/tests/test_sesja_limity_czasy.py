"""
F16, część 3: jedno uwierzytelnienie na żądanie, limit panelu oddzielony od limitu
czatu, pomiar wolnych żądań.

Pomiar z 15.09.2026 (żądanie panelu z prawdziwym JWT): /api/accounts/me/ robiło
7 zapytań, z czego 3 powtórzone - TenantMiddleware i DRF osobno czytały
użytkownika, sesję logowania i firmę. Limit czatu (30/min bez aktywnego planu)
obowiązywał na każdym ekranie panelu.
"""

import logging
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import URLPattern, URLResolver
from rest_framework.test import APIClient

from accounts.models import CustomUser, Subscription, Tenant
from accounts.sessions import LoginSession
from api.session_tokens import SessionJWTAuthentication, SessionRefreshToken
from api.throttles import APIKeyRateThrottle


@pytest.fixture(autouse=True)
def czyste_liczniki():
    cache.clear()
    yield
    cache.clear()


def firma(nazwa="Firma", aktywna=True):
    tenant = Tenant.objects.create(name=nazwa, owner_email=f"szef-{nazwa}@firma.pl")
    Subscription.objects.create(
        tenant=tenant,
        plan_type="pro",
        is_active=aktywna,
        message_limit=25_000,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=30),
    )
    return tenant


def wlasciciel(tenant, nazwa="szef"):
    user = CustomUser.objects.create_user(
        username=f"{nazwa}-{tenant.id}",
        email=f"{nazwa}-{tenant.id}@firma.pl",
        password="x",
        tenant=tenant,
    )
    user.role = "owner"
    user.save()
    return user


def token_dostepu(user):
    return str(SessionRefreshToken.for_user(user).access_token)


def zapytania_o(tabela, zapytania):
    return [z for z in zapytania.captured_queries if f'from "{tabela}"' in z["sql"].lower()]


@pytest.mark.django_db
class TestJednegoUwierzytelnienia:
    @pytest.mark.parametrize("adres", ["/api/accounts/me/", "/api/faq/", "/api/billing/plans/"])
    def test_sesja_i_uzytkownik_czytane_raz(self, adres):
        tenant = firma()
        klient = APIClient()
        klient.credentials(HTTP_AUTHORIZATION=f"Bearer {token_dostepu(wlasciciel(tenant))}")

        with CaptureQueriesContext(connection) as zapytania:
            odpowiedz = klient.get(adres)

        assert odpowiedz.status_code == 200
        assert len(zapytania_o("accounts_loginsession", zapytania)) == 1
        assert len(zapytania_o("accounts_customuser", zapytania)) == 1

    def test_odwolana_sesja_nadal_odrzucona(self):
        """Straż: zapamiętanie wyniku nie może przepuścić odwołanej sesji."""
        tenant = firma()
        user = wlasciciel(tenant)
        token = token_dostepu(user)
        LoginSession.objects.filter(user=user).update(revoked_at=date.today())
        klient = APIClient()
        klient.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        assert klient.get("/api/accounts/me/").status_code == 401

    def test_inny_naglowek_na_tym_samym_zadaniu_sprawdzany_od_nowa(self):
        tenant = firma()
        pierwszy, drugi = wlasciciel(tenant, "a"), wlasciciel(tenant, "b")
        zadanie = RequestFactory().get(
            "/api/accounts/me/", HTTP_AUTHORIZATION=f"Bearer {token_dostepu(pierwszy)}"
        )
        uwierzytelnienie = SessionJWTAuthentication()

        assert uwierzytelnienie.authenticate(zadanie)[0] == pierwszy
        zadanie.META["HTTP_AUTHORIZATION"] = f"Bearer {token_dostepu(drugi)}"
        assert uwierzytelnienie.authenticate(zadanie)[0] == drugi


def widoki_widgetu():
    """Klasy widoków pod /api/widget/ i /api/widget-settings/ (bez panelowego mine/)."""
    from api import urls

    wynik = {}

    def przejdz(wzorce, prefiks=""):
        for wzorzec in wzorce:
            sciezka = prefiks + str(wzorzec.pattern)
            if isinstance(wzorzec, URLResolver):
                przejdz(wzorzec.url_patterns, sciezka)
            elif isinstance(wzorzec, URLPattern):
                klasa = getattr(wzorzec.callback, "view_class", None)
                publiczna = sciezka.startswith("widget/") or sciezka == "widget-settings/"
                if klasa is not None and publiczna:
                    wynik[sciezka] = klasa

    przejdz(urls.urlpatterns)
    return wynik


class TestLimitow:
    def test_domyslnie_obowiazuje_limit_panelu_a_nie_czatu(self):
        # dev.py dokłada ScopedRateThrottle, dlatego bez porównania całej listy
        domyslne = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"]
        assert "api.throttles.SubscriptionRateThrottle" in domyslne
        assert "api.throttles.APIKeyRateThrottle" not in domyslne

    def test_kazdy_publiczny_widok_widgetu_ma_limit_czatu(self):
        # Gdyby nowy widok widgetu go nie ustawił, po zmianie domyślnych limitów
        # odwiedzający dostałby dziesięciokrotnie luźniejszy limit panelu.
        widoki = widoki_widgetu()
        assert len(widoki) >= 6, widoki
        bez_limitu = sorted(
            sciezka
            for sciezka, klasa in widoki.items()
            if APIKeyRateThrottle not in (klasa.throttle_classes or [])
        )
        assert bez_limitu == []

    @pytest.mark.django_db
    def test_firma_bez_aktywnego_planu_moze_pracowac_w_panelu(self):
        # Stawka czatu bez aktywnego planu to 30 na minutę na cały panel.
        tenant = firma(aktywna=False)
        klient = APIClient()
        klient.force_authenticate(user=wlasciciel(tenant))
        klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))

        kody = [klient.get("/api/analytics/").status_code for _ in range(40)]

        assert set(kody) == {200}

    @pytest.mark.django_db
    def test_widget_nadal_dostaje_429_po_limicie_czatu(self):
        tenant = firma()
        klient = APIClient()
        klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))

        with patch.object(APIKeyRateThrottle, "get_plan_rate", return_value="2/min"):
            kody = [klient.get("/api/widget/faq/").status_code for _ in range(3)]

        assert kody == [200, 200, 429]


@pytest.mark.django_db
class TestPomiaruCzasu:
    def test_wolne_zadanie_zostawia_linie_z_trasa_czasem_i_zapytaniami(self, caplog, settings):
        settings.WOLNE_ZADANIE_MS = 1000
        tenant = firma()
        klient = APIClient()
        klient.force_authenticate(user=wlasciciel(tenant))
        klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))

        with (
            patch("chatbot_project.pomiar_czasu.perf_counter", side_effect=[0.0, 2.5]),
            caplog.at_level(logging.WARNING, logger="chatbot_project.pomiar_czasu"),
        ):
            klient.get("/api/documents/987654/?szukaj=tajne")

        linie = [r.getMessage() for r in caplog.records if r.name == "chatbot_project.pomiar_czasu"]
        assert len(linie) == 1
        # Trasa jako wzorzec routera, bez identyfikatora z adresu
        assert "GET api/documents/(?P<pk>[^/.]+)/$ -> 404 w 2500 ms, zapytań SQL:" in linie[0]
        # Bez identyfikatorów i parametrów z adresu
        assert "987654" not in linie[0] and "tajne" not in linie[0]

    def test_szybkie_zadanie_bez_wpisu(self, caplog, settings):
        settings.WOLNE_ZADANIE_MS = 1000
        tenant = firma()
        klient = APIClient()
        klient.force_authenticate(user=wlasciciel(tenant))
        klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))

        with (
            patch("chatbot_project.pomiar_czasu.perf_counter", side_effect=[0.0, 0.2]),
            caplog.at_level(logging.WARNING, logger="chatbot_project.pomiar_czasu"),
        ):
            klient.get("/api/faq/")

        assert [r for r in caplog.records if r.name == "chatbot_project.pomiar_czasu"] == []

    def test_liczba_zapytan_w_linii_jest_prawdziwa(self, caplog, settings):
        settings.WOLNE_ZADANIE_MS = 1000
        tenant = firma()
        klient = APIClient()
        klient.force_authenticate(user=wlasciciel(tenant))
        klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))

        with (
            CaptureQueriesContext(connection) as zapytania,
            patch("chatbot_project.pomiar_czasu.perf_counter", side_effect=[0.0, 5.0]),
            caplog.at_level(logging.WARNING, logger="chatbot_project.pomiar_czasu"),
        ):
            klient.get("/api/analytics/")

        linia = next(
            r.getMessage() for r in caplog.records if r.name == "chatbot_project.pomiar_czasu"
        )
        assert linia.endswith(f"zapytań SQL: {len(zapytania)}")
