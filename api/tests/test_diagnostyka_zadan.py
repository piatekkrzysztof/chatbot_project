"""
Diagnostyka zadań w tle.

Wartość tego endpointu leży w werdykcie, a nie w surowych danych — więc to
werdykt trzeba przetestować. Jeśli powie „wszystko działa" przy zaległych
rozmowach albo „nie działa" przy świeżo pobranej stronie, jest gorszy niż
jego brak: usypia czujność zamiast ją budzić.

Cztery stany, w których produkcja może się znaleźć, i cztery różne odpowiedzi.
"""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import CustomUser, Tenant
from api.views import diagnostyka_zadan as dz
from chat.models import Conversation
from documents.models import WebsiteSource


BROKER_OK = {"broker_osiagalny": True, "odpowiedzialo_workerow": 1, "nazwy": ["celery@render"]}
BROKER_BRAK_WORKERA = {"broker_osiagalny": True, "odpowiedzialo_workerow": 0, "nazwy": []}
BROKER_PADL = {"broker_osiagalny": False, "odpowiedzialo_workerow": 0, "nazwy": [],
               "blad": "ConnectionError: nie można połączyć"}


def zaloguj(tenant):
    user = CustomUser.objects.create_user(
        username="wlasciciel@example.com", email="wlasciciel@example.com",
        password="tajne123", tenant=tenant, role="owner",
    )
    klient = APIClient()
    klient.force_authenticate(user=user)
    # TenantMiddleware działa przed widokiem, więc samo force_authenticate
    # nie wystarcza — bez klucza żądanie odpada na 401 „Nie rozpoznano tenanta".
    klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))
    return klient


def odpytaj(klient, broker):
    with patch.object(dz, "_stan_brokera", return_value=broker):
        return klient.get("/api/diagnostyka/zadania/")


@pytest.mark.django_db
class TestWerdyktu:
    def test_swieze_pobranie_i_brak_zaleglosci_to_wszystko_dziala(self):
        tenant = Tenant.objects.create(name="Firma", data_retention_days=90)
        WebsiteSource.objects.create(
            tenant=tenant, name="strona", url="https://example.com",
            is_active=True, last_crawled_at=timezone.now() - timedelta(hours=3),
        )
        odp = odpytaj(zaloguj(tenant), BROKER_OK)

        assert odp.status_code == 200
        assert "Wszystko działa" in odp.data["werdykt"]
        assert odp.data["slady_w_danych"]["pobieranie_stron"]["wniosek"] == "dziala"
        assert odp.data["slady_w_danych"]["czyszczenie_rodo"]["wniosek"] == "dziala"

    def test_stare_pobranie_zdradza_ze_beat_nie_chodzi(self):
        """Najważniejszy przypadek: broker odpowiada, więc bez śladów w danych
        wyglądałoby to na sprawne. Harmonogram jednak nie był wykonywany."""
        tenant = Tenant.objects.create(name="Firma", data_retention_days=90)
        WebsiteSource.objects.create(
            tenant=tenant, name="strona", url="https://example.com",
            is_active=True, last_crawled_at=timezone.now() - timedelta(hours=50),
        )
        odp = odpytaj(zaloguj(tenant), BROKER_OK)

        assert "ZADANIA CYKLICZNE NIE DZIAŁAJĄ" in odp.data["werdykt"]
        assert "celery-beat" in odp.data["werdykt"]

    def test_zalegle_rozmowy_zdradzaja_ze_czyszczenie_rodo_nie_chodzi(self):
        tenant = Tenant.objects.create(name="Firma", data_retention_days=30)
        WebsiteSource.objects.create(
            tenant=tenant, name="strona", url="https://example.com",
            is_active=True, last_crawled_at=timezone.now() - timedelta(hours=2),
        )
        stara = Conversation.objects.create(tenant=tenant, user_identifier="gosc")
        # auto_now_add trzeba obejść, żeby udać rozmowę sprzed 60 dni
        Conversation.objects.filter(pk=stara.pk).update(
            started_at=timezone.now() - timedelta(days=60)
        )
        odp = odpytaj(zaloguj(tenant), BROKER_OK)

        assert "ZADANIA CYKLICZNE NIE DZIAŁAJĄ" in odp.data["werdykt"]
        czyszczenie = odp.data["slady_w_danych"]["czyszczenie_rodo"]
        assert czyszczenie["wniosek"] == "nie-dziala"
        assert czyszczenie["zaleglych_rozmow"] == 1

    def test_retencja_wylaczona_nie_jest_zaleglosc(self):
        """0 dni znaczy „nie usuwaj" — stara rozmowa jest wtedy w porządku."""
        tenant = Tenant.objects.create(name="Firma", data_retention_days=0)
        stara = Conversation.objects.create(tenant=tenant, user_identifier="gosc")
        Conversation.objects.filter(pk=stara.pk).update(
            started_at=timezone.now() - timedelta(days=400)
        )
        odp = odpytaj(zaloguj(tenant), BROKER_OK)

        assert odp.data["slady_w_danych"]["czyszczenie_rodo"]["zaleglych_rozmow"] == 0

    def test_nieosiagalny_broker_wskazuje_redis(self):
        tenant = Tenant.objects.create(name="Firma", data_retention_days=90)
        odp = odpytaj(zaloguj(tenant), BROKER_PADL)

        assert "BROKER NIEOSIĄGALNY" in odp.data["werdykt"]
        assert "REDIS_URL" in odp.data["werdykt"]

    def test_broker_bez_workera_to_inna_diagnoza_niz_brak_brokera(self):
        tenant = Tenant.objects.create(name="Firma", data_retention_days=90)
        odp = odpytaj(zaloguj(tenant), BROKER_BRAK_WORKERA)

        assert "ŻADEN WORKER NIE ODPOWIADA" in odp.data["werdykt"]
        assert "celery-worker" in odp.data["werdykt"]

    def test_bez_zrodel_www_nie_udajemy_ze_wiemy(self):
        """Brak danych to nie to samo co dowód sprawności."""
        tenant = Tenant.objects.create(name="Firma", data_retention_days=90)
        odp = odpytaj(zaloguj(tenant), BROKER_OK)

        assert odp.data["slady_w_danych"]["pobieranie_stron"]["wniosek"] == "brak-danych"
        assert "Nie ma jeszcze danych" in odp.data["werdykt"]


@pytest.mark.django_db
class TestDostepu:
    def test_niezalogowany_nie_zobaczy_stanu_zaplecza(self):
        odp = APIClient().get("/api/diagnostyka/zadania/")
        assert odp.status_code in (401, 403)


@pytest.mark.django_db
class TestOdpornosci:
    def test_padniety_broker_nie_wywraca_endpointu(self):
        """_stan_brokera łapie wszystko — diagnostyka ma działać zwłaszcza
        wtedy, gdy zaplecze nie działa."""
        tenant = Tenant.objects.create(name="Firma", data_retention_days=90)
        klient = zaloguj(tenant)

        with patch("chatbot_project.celery.app.connection", side_effect=OSError("brak sieci")):
            odp = klient.get("/api/diagnostyka/zadania/")

        assert odp.status_code == 200
        assert odp.data["broker_i_workery"]["broker_osiagalny"] is False
