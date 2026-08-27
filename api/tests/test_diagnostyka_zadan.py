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
BROKER_PADL = {
    "broker_osiagalny": False,
    "odpowiedzialo_workerow": 0,
    "nazwy": [],
    "blad": "ConnectionError: nie można połączyć",
}


def zaloguj(tenant):
    user = CustomUser.objects.create_user(
        username="wlasciciel@example.com",
        email="wlasciciel@example.com",
        password="tajne123",
        tenant=tenant,
        role="owner",
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
        """„Wszystko działa" wymaga dowodu z OBU sygnałów. Sama świeżo pobrana
        strona nie wystarcza — bez rozmowy w okolicy progu retencji nie wiadomo,
        czy czyszczenie w ogóle miało co robić."""
        tenant = Tenant.objects.create(name="Firma", data_retention_days=30)
        WebsiteSource.objects.create(
            tenant=tenant,
            name="strona",
            url="https://example.com",
            is_active=True,
            last_crawled_at=timezone.now() - timedelta(hours=3),
        )
        blisko_progu = Conversation.objects.create(tenant=tenant, user_identifier="gosc")
        Conversation.objects.filter(pk=blisko_progu.pk).update(
            started_at=timezone.now() - timedelta(days=27)
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
            tenant=tenant,
            name="strona",
            url="https://example.com",
            is_active=True,
            last_crawled_at=timezone.now() - timedelta(hours=50),
        )
        odp = odpytaj(zaloguj(tenant), BROKER_OK)

        # Werdykt musi nazwać, KTÓRY sygnał leży — inaczej przy dwóch
        # zadaniach cyklicznych nie wiadomo, gdzie szukać.
        assert "NIE DZIAŁA: pobieranie stron" in odp.data["werdykt"]
        assert "celery-worker" in odp.data["werdykt"]

    def test_zalegle_rozmowy_zdradzaja_ze_czyszczenie_rodo_nie_chodzi(self):
        tenant = Tenant.objects.create(name="Firma", data_retention_days=30)
        WebsiteSource.objects.create(
            tenant=tenant,
            name="strona",
            url="https://example.com",
            is_active=True,
            last_crawled_at=timezone.now() - timedelta(hours=2),
        )
        stara = Conversation.objects.create(tenant=tenant, user_identifier="gosc")
        # auto_now_add trzeba obejść, żeby udać rozmowę sprzed 60 dni
        Conversation.objects.filter(pk=stara.pk).update(
            started_at=timezone.now() - timedelta(days=60)
        )
        odp = odpytaj(zaloguj(tenant), BROKER_OK)

        assert "NIE DZIAŁA: czyszczenie RODO" in odp.data["werdykt"]
        czyszczenie = odp.data["slady_w_danych"]["czyszczenie_rodo"]
        assert czyszczenie["wniosek"] == "nie-dziala"
        assert czyszczenie["zaleglych_rozmow"] == 1

    def test_mloda_baza_nie_jest_dowodem_ze_czyszczenie_dziala(self):
        """Znalezione na produkcji: przy retencji 90 dni i najstarszej rozmowie
        sprzed tygodnia sprawdzian mówił „działa", choć nie było czego kasować.
        Miernik, który raportuje sukces bez dowodu, jest gorszy niż jego brak."""
        tenant = Tenant.objects.create(name="Firma", data_retention_days=90)
        swieza = Conversation.objects.create(tenant=tenant, user_identifier="gosc")
        Conversation.objects.filter(pk=swieza.pk).update(
            started_at=timezone.now() - timedelta(days=7)
        )
        odp = odpytaj(zaloguj(tenant), BROKER_OK)

        assert odp.data["slady_w_danych"]["czyszczenie_rodo"]["wniosek"] == "brak-danych"

    def test_rozmowy_przy_progu_i_zero_zaleglosci_to_dowod(self):
        """Dopiero gdy coś było blisko progu i nie przekroczyło go — wiemy,
        że czyszczenie faktycznie chodzi."""
        tenant = Tenant.objects.create(name="Firma", data_retention_days=30)
        blisko = Conversation.objects.create(tenant=tenant, user_identifier="gosc")
        Conversation.objects.filter(pk=blisko.pk).update(
            started_at=timezone.now() - timedelta(days=27)
        )
        odp = odpytaj(zaloguj(tenant), BROKER_OK)

        assert odp.data["slady_w_danych"]["czyszczenie_rodo"]["wniosek"] == "dziala"

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

    def test_nigdy_nie_probowano_to_nie_to_samo_co_awaria(self):
        """Znalezione na produkcji: po uruchomieniu workera źródła nadal miały
        puste last_crawled_at, bo nikt nie zlecił zadania. Werdykt krzyczał
        „nie działa", choć zaplecze było już sprawne — i wysyłał do naprawiania
        czegoś, co nie było zepsute."""
        tenant = Tenant.objects.create(name="Firma", data_retention_days=90)
        WebsiteSource.objects.create(
            tenant=tenant,
            name="strona",
            url="https://example.com",
            is_active=True,
        )
        odp = odpytaj(zaloguj(tenant), BROKER_OK)

        assert odp.data["slady_w_danych"]["pobieranie_stron"]["wniosek"] == "nie-probowano"
        assert "nie zostało jeszcze zlecone" in odp.data["werdykt"]

    def test_zapisany_blad_wskazuje_na_crawler_a_nie_na_zaplecze(self):
        """Gdy próba była i się nie udała, wina leży gdzie indziej niż
        w Renderze — werdykt musi kierować do crawlera, nie do usług."""
        tenant = Tenant.objects.create(name="Firma", data_retention_days=90)
        WebsiteSource.objects.create(
            tenant=tenant,
            name="strona",
            url="https://example.com",
            is_active=True,
            last_attempt_at=timezone.now() - timedelta(minutes=5),
            last_error="SSLError: certificate verify failed",
        )
        odp = odpytaj(zaloguj(tenant), BROKER_OK)

        pobieranie = odp.data["slady_w_danych"]["pobieranie_stron"]
        assert pobieranie["wniosek"] == "nie-dziala"
        assert "SSLError" in pobieranie["przyklad_bledu"]
        assert "nie zaplecza" in pobieranie["opis"]

    def test_swieze_pobranie_przy_mlodej_bazie_nie_kaze_dodawac_zrodel(self):
        """Odczyt z produkcji 14.08: strony pobrane minutę wcześniej, a werdykt
        kazał „dodać źródło WWW i sprawdzić za dwanaście godzin". Komunikat
        o braku danych był zaszyty pod pobieranie, a odpaliła go retencja.
        Diagnostyka, która myli sygnały, kieruje w złe miejsce."""
        tenant = Tenant.objects.create(name="Firma", data_retention_days=90)
        WebsiteSource.objects.create(
            tenant=tenant,
            name="strona",
            url="https://example.com",
            is_active=True,
            last_crawled_at=timezone.now() - timedelta(minutes=1),
        )
        odp = odpytaj(zaloguj(tenant), BROKER_OK)
        werdykt = odp.data["werdykt"]

        assert "dodaj źródło WWW" not in werdykt
        assert "Potwierdzone: pobieranie stron" in werdykt
        assert "czyszczenie RODO" in werdykt

    def test_bez_zrodel_www_nie_udajemy_ze_wiemy(self):
        """Brak danych to nie to samo co dowód sprawności."""
        tenant = Tenant.objects.create(name="Firma", data_retention_days=90)
        odp = odpytaj(zaloguj(tenant), BROKER_OK)

        assert odp.data["slady_w_danych"]["pobieranie_stron"]["wniosek"] == "brak-danych"
        assert "Nie da się jeszcze potwierdzić" in odp.data["werdykt"]
        assert "pobieranie stron" in odp.data["werdykt"]


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


@pytest.mark.django_db
class TestPoziomu:
    """Poziom steruje kolorem w panelu, więc musi się zgadzać z treścią
    werdyktu. Dwie definicje powagi — tu i w przeglądarce — rozjechałyby się."""

    def test_awaria_gdy_slady_pokazuja_usterke(self):
        tenant = Tenant.objects.create(name="Firma", data_retention_days=90)
        WebsiteSource.objects.create(
            tenant=tenant,
            name="strona",
            url="https://example.com",
            is_active=True,
            last_crawled_at=timezone.now() - timedelta(hours=50),
        )
        assert odpytaj(zaloguj(tenant), BROKER_OK).data["poziom"] == "awaria"

    def test_awaria_gdy_brak_workera(self):
        tenant = Tenant.objects.create(name="Firma", data_retention_days=90)
        WebsiteSource.objects.create(
            tenant=tenant,
            name="strona",
            url="https://example.com",
            is_active=True,
            last_crawled_at=timezone.now() - timedelta(hours=2),
        )
        assert odpytaj(zaloguj(tenant), BROKER_BRAK_WORKERA).data["poziom"] == "awaria"

    def test_uwaga_gdy_czegos_nie_da_sie_potwierdzic(self):
        tenant = Tenant.objects.create(name="Firma", data_retention_days=90)
        WebsiteSource.objects.create(
            tenant=tenant,
            name="strona",
            url="https://example.com",
            is_active=True,
            last_crawled_at=timezone.now() - timedelta(minutes=5),
        )
        assert odpytaj(zaloguj(tenant), BROKER_OK).data["poziom"] == "uwaga"

    def test_ok_dopiero_gdy_oba_sygnaly_potwierdzone(self):
        tenant = Tenant.objects.create(name="Firma", data_retention_days=30)
        WebsiteSource.objects.create(
            tenant=tenant,
            name="strona",
            url="https://example.com",
            is_active=True,
            last_crawled_at=timezone.now() - timedelta(hours=1),
        )
        blisko = Conversation.objects.create(tenant=tenant, user_identifier="gosc")
        Conversation.objects.filter(pk=blisko.pk).update(
            started_at=timezone.now() - timedelta(days=27)
        )
        assert odpytaj(zaloguj(tenant), BROKER_OK).data["poziom"] == "ok"


@pytest.mark.django_db
class TestIzolacjiKlientow:
    """Endpoint jest dostępny dla każdego właściciela konta, nie tylko dla nas.
    Klient nie może zobaczyć w nim danych innej firmy — ani liczby jej źródeł,
    ani tym bardziej adresu jej strony w treści błędu."""

    def test_nie_widac_zrodel_innej_firmy(self):
        obcy = Tenant.objects.create(name="Konkurencja", data_retention_days=90)
        WebsiteSource.objects.create(
            tenant=obcy,
            name="tajny-projekt.pl",
            url="https://tajny-projekt.pl",
            is_active=True,
            last_attempt_at=timezone.now(),
            last_error="SSLError: sekret w komunikacie",
        )
        moj = Tenant.objects.create(name="Moja firma", data_retention_days=90)
        odp = odpytaj(zaloguj(moj), BROKER_OK)

        pobieranie = odp.data["slady_w_danych"]["pobieranie_stron"]
        assert pobieranie["aktywnych_zrodel"] == 0
        assert "tajny-projekt" not in str(odp.data)
        assert "sekret" not in str(odp.data)

    def test_nie_widac_zaleglych_rozmow_innej_firmy(self):
        obcy = Tenant.objects.create(name="Konkurencja", data_retention_days=30)
        stara = Conversation.objects.create(tenant=obcy, user_identifier="gosc")
        Conversation.objects.filter(pk=stara.pk).update(
            started_at=timezone.now() - timedelta(days=90)
        )
        moj = Tenant.objects.create(name="Moja firma", data_retention_days=30)
        odp = odpytaj(zaloguj(moj), BROKER_OK)

        assert odp.data["slady_w_danych"]["czyszczenie_rodo"]["zaleglych_rozmow"] == 0


@pytest.mark.django_db
class TestSpojnosciWerdyktuIPoziomu:
    def test_brak_workera_wygrywa_z_nieprobowanym(self):
        """Wyłapane na żywo: werdykt oznajmiał „zaplecze działa (worker
        odpowiada: 0)" — zdanie wewnętrznie sprzeczne, w dodatku niezgodne
        z polem poziom, które w tej samej sytuacji zwracało awarię."""
        tenant = Tenant.objects.create(name="Firma", data_retention_days=90)
        WebsiteSource.objects.create(
            tenant=tenant,
            name="strona",
            url="https://example.com",
            is_active=True,
        )
        odp = odpytaj(zaloguj(tenant), BROKER_BRAK_WORKERA)

        assert odp.data["poziom"] == "awaria"
        assert "Zaplecze działa" not in odp.data["werdykt"]
        assert "ŻADEN WORKER NIE ODPOWIADA" in odp.data["werdykt"]

    @pytest.mark.parametrize("broker", [BROKER_PADL, BROKER_BRAK_WORKERA])
    def test_poziom_awaria_zawsze_ma_werdykt_o_awarii(self, broker):
        """Kolor i treść muszą mówić to samo — inaczej panel pokazuje
        czerwony pasek z uspokajającym zdaniem."""
        tenant = Tenant.objects.create(name="Firma", data_retention_days=90)
        WebsiteSource.objects.create(
            tenant=tenant,
            name="strona",
            url="https://example.com",
            is_active=True,
        )
        odp = odpytaj(zaloguj(tenant), broker)

        assert odp.data["poziom"] == "awaria"
        assert odp.data["werdykt"].split(".")[0].isupper() or "NIE" in odp.data["werdykt"]
