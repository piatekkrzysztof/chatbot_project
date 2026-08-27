"""
Rozpoznanie adresu odwiedzającego zza serwerów pośredniczących.

Na produkcji ruch idzie przez Cloudflare i load balancer Rendera, więc
REMOTE_ADDR to adres proxy, a nie odwiedzającego — dotąd wszyscy zlewali się
w jedną tożsamość. Psuło to identyfikator rozmówcy zapisywany przy rozmowie,
a przy limicie na odwiedzającego oznaczałoby zablokowanie widgetu wszystkim
klientom naraz po kilkunastu zapytaniach.

X-Forwarded-For nie wolno czytać naiwnie: klient może wysłać własny nagłówek,
a proxy tylko dopisuje kolejne wpisy na końcu. Wiarygodne są wyłącznie wpisy
dopisane przez nasze proxy, czyli TRUSTED_PROXY_DEPTH ostatnich.
"""

import uuid

import pytest
from django.test import RequestFactory, override_settings
from rest_framework.test import APIClient

from chat.privacy import client_ip, visitor_identifier


def zadanie(remote_addr="10.0.0.1", forwarded=None):
    naglowki = {"REMOTE_ADDR": remote_addr}
    if forwarded is not None:
        naglowki["HTTP_X_FORWARDED_FOR"] = forwarded
    return RequestFactory().get("/", **naglowki)


class TestBezProxy:
    @override_settings(TRUSTED_PROXY_DEPTH=0)
    def test_bierzemy_remote_addr(self):
        assert client_ip(zadanie(remote_addr="203.0.113.7")) == "203.0.113.7"

    @override_settings(TRUSTED_PROXY_DEPTH=0)
    def test_naglowek_od_klienta_jest_ignorowany(self):
        """
        Bez proxy X-Forwarded-For może pochodzić wyłącznie od klienta,
        więc zaufanie mu pozwoliłoby dowolnie podszyć się pod inny adres.
        """
        request = zadanie(remote_addr="203.0.113.7", forwarded="1.2.3.4")

        assert client_ip(request) == "203.0.113.7"


class TestZaProxy:
    @override_settings(TRUSTED_PROXY_DEPTH=2)
    def test_bierzemy_adres_dopisany_przez_najdalsze_zaufane_proxy(self):
        """
        Łańcuch bez podszycia: klient -> Cloudflare -> load balancer.
        Cloudflare dopisał adres klienta, load balancer adres Cloudflare.
        """
        request = zadanie(remote_addr="10.0.0.1", forwarded="203.0.113.7, 172.16.0.1")

        assert client_ip(request) == "203.0.113.7"

    @override_settings(TRUSTED_PROXY_DEPTH=2)
    def test_podrobiony_naglowek_nie_zmienia_wyniku(self):
        """
        Sedno zabezpieczenia. Klient wysyła własny X-Forwarded-For, proxy
        dopisują swoje wpisy za nim — liczone od końca trafiamy w prawdziwy
        adres, a podrobiony wpis zostaje z przodu i jest ignorowany.
        """
        request = zadanie(
            remote_addr="10.0.0.1",
            forwarded="9.9.9.9, 203.0.113.7, 172.16.0.1",
        )

        assert client_ip(request) == "203.0.113.7"

    @override_settings(TRUSTED_PROXY_DEPTH=2)
    def test_brak_naglowka_mimo_konfiguracji(self):
        """Żądanie z pominięciem load balancera — zostaje REMOTE_ADDR."""
        assert client_ip(zadanie(remote_addr="10.0.0.1")) == "10.0.0.1"

    @override_settings(TRUSTED_PROXY_DEPTH=2)
    def test_krotszy_lancuch_niz_konfiguracja(self):
        """Nie sięgamy poza początek listy, choćby konfiguracja na to wskazywała."""
        assert client_ip(zadanie(forwarded="203.0.113.7")) == "203.0.113.7"

    @override_settings(TRUSTED_PROXY_DEPTH=2)
    def test_spacje_i_puste_wpisy_nie_psuja_odczytu(self):
        request = zadanie(forwarded="  203.0.113.7 ,, 172.16.0.1  ")

        assert client_ip(request) == "203.0.113.7"


class TestIdentyfikatoraRozmowcy:
    @override_settings(TRUSTED_PROXY_DEPTH=2)
    def test_rozni_odwiedzajacy_maja_rozne_identyfikatory(self):
        """
        To był realny skutek błędu: za proxy wszystkie rozmowy dostawały
        ten sam identyfikator, więc nie dało się ich od siebie odróżnić.
        """
        pierwszy = visitor_identifier(zadanie(forwarded="203.0.113.7, 172.16.0.1"))
        drugi = visitor_identifier(zadanie(forwarded="198.51.100.4, 172.16.0.1"))

        assert pierwszy != drugi

    @override_settings(TRUSTED_PROXY_DEPTH=2)
    def test_identyfikator_pozostaje_zanonimizowany(self):
        """Poprawka nie może cofnąć minimalizacji danych — RODO."""
        identyfikator = visitor_identifier(zadanie(forwarded="203.0.113.7, 172.16.0.1"))

        assert identyfikator == "203.0.113.0"


@pytest.mark.django_db
class TestLimituOdwiedzajacego:
    URL = "/api/widget/chat/"

    def wyslij(self, tenant, forwarded, klient):
        return klient.post(
            self.URL,
            {"message": "Pytanie", "conversation_session_id": str(uuid.uuid4())},
            format="json",
            HTTP_X_API_KEY=str(tenant.api_key),
            HTTP_X_FORWARDED_FOR=forwarded,
        )

    @override_settings(TRUSTED_PROXY_DEPTH=2, LIMIT_ODWIEDZAJACEGO="3/hour")
    def test_natretny_odwiedzajacy_zostaje_zatrzymany(self, tenant, subscribtion, mocker, settings):
        """
        Bez tego limitu jeden rozmówca mógł sam wyczerpać cały miesięczny
        pakiet, za który zapłacił klient.
        """
        mocker.patch(
            "api.utils.chat_engine.get_openai_response",
            return_value={"content": "ok", "tokens": 5},
        )
        klient = APIClient()
        adres = "203.0.113.7, 172.16.0.1"

        kody = [self.wyslij(tenant, adres, klient).status_code for _ in range(4)]

        assert kody[:3] == [200, 200, 200]
        assert kody[3] == 429

    @override_settings(TRUSTED_PROXY_DEPTH=2, LIMIT_ODWIEDZAJACEGO="3/hour")
    def test_limit_jednego_nie_dotyka_pozostalych(self, tenant, subscribtion, mocker, settings):
        """Sedno całej poprawki z adresem — inaczej blokada objęłaby wszystkich."""
        mocker.patch(
            "api.utils.chat_engine.get_openai_response",
            return_value={"content": "ok", "tokens": 5},
        )
        klient = APIClient()
        natretny = "203.0.113.7, 172.16.0.1"

        for _ in range(4):
            self.wyslij(tenant, natretny, klient)

        inny = self.wyslij(tenant, "198.51.100.4, 172.16.0.1", klient)

        assert inny.status_code == 200


@pytest.mark.django_db
class TestDiagnostyki:
    URL = "/api/diagnostyka/adres/"

    def zalogowany(self, user, tenant):
        user.tenant = tenant
        user.role = "owner"
        user.save()
        klient = APIClient()
        klient.force_authenticate(user=user)
        # TenantMiddleware działa przed widokiem, więc samo force_authenticate
        # mu nie wystarcza — tak samo robią pozostałe testy panelu
        klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))
        return klient

    @override_settings(TRUSTED_PROXY_DEPTH=2)
    def test_pokazuje_rozpoznany_adres(self, user, tenant):
        response = self.zalogowany(user, tenant).get(
            self.URL, HTTP_X_FORWARDED_FOR="203.0.113.7, 172.16.0.1"
        )

        assert response.status_code == 200
        dane = response.json()
        assert dane["rozpoznany_adres"] == "203.0.113.7"
        assert dane["trusted_proxy_depth"] == 2

    @override_settings(TRUSTED_PROXY_DEPTH=0)
    def test_ostrzega_o_zlej_konfiguracji(self, user, tenant):
        """Podpowiedź ma wprost wskazać właściwą wartość, a nie tylko fakt błędu."""
        response = self.zalogowany(user, tenant).get(
            self.URL, HTTP_X_FORWARDED_FOR="203.0.113.7, 172.16.0.1"
        )

        assert "2" in response.json()["podpowiedz"]

    def test_niezalogowany_nie_ma_wstepu(self):
        assert APIClient().get(self.URL).status_code in (401, 403)
