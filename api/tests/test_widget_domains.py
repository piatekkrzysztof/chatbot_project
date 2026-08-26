"""
Rejestr witryn, na których działa widget, i limit domen z cennika.

Cennik obiecuje 1/3/10 domen, ale nic nie wiedziało, gdzie widgety faktycznie
działają. Przy okazji zamyka to realną dziurę: klucz API jest widoczny w kodzie
strony klienta, więc bez tej listy każdy mógł go skopiować i zużywać cudzy
limit wiadomości na własnej stronie.

Adres bierzemy z nagłówka Origin, bo strona nie może go podrobić. Rejestr
siedzi na endpoincie ustawień, bo to jedyne zapytanie widgetu niosące
prawdziwy adres witryny — samo okno czatu działa w ramce na naszej domenie.
"""
import pytest
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from accounts.domains import limit_domen, normalizuj_host, zarejestruj_domene
from accounts.models import WidgetDomain


class TestNormalizacji:
    @pytest.mark.parametrize("origin,host", [
        ("https://sklep.pl", "sklep.pl"),
        ("https://www.sklep.pl", "sklep.pl"),
        ("http://SKLEP.PL", "sklep.pl"),
        ("https://sklep.pl:8443", "sklep.pl"),
        ("sklep.pl", "sklep.pl"),
        ("https://sub.sklep.pl", "sub.sklep.pl"),
    ])
    def test_sprowadza_do_samej_nazwy_hosta(self, origin, host):
        assert normalizuj_host(origin) == host

    def test_www_i_bez_www_to_ta_sama_witryna(self):
        """
        Bez tego klient planu Start wyczerpałby limit na własnej stronie
        głównej, bo część odwiedzających wchodzi z www, a część bez.
        """
        assert normalizuj_host("https://www.sklep.pl") == normalizuj_host("https://sklep.pl")

    @pytest.mark.parametrize("wartosc", ["", None, "   "])
    def test_brak_adresu_daje_pusty_host(self, wartosc):
        assert normalizuj_host(wartosc) == ""


@pytest.mark.django_db
class TestRejestracji:
    def test_pierwsze_zapytanie_zapisuje_witryne(self, tenant, subscribtion):
        subscribtion.plan_type = "grow"
        subscribtion.save()

        zarejestruj_domene(tenant, "https://sklep.pl")

        assert WidgetDomain.objects.filter(tenant=tenant, host="sklep.pl").exists()

    def test_kolejne_zapytania_nie_dubluja(self, tenant, subscribtion):
        subscribtion.plan_type = "grow"
        subscribtion.save()

        for _ in range(5):
            zarejestruj_domene(tenant, "https://sklep.pl")

        assert WidgetDomain.objects.filter(tenant=tenant).count() == 1

    def test_adresy_deweloperskie_nie_zajmuja_miejsca(self, tenant, subscribtion):
        """
        Klient stawiający stronę lokalnie zużyłby na testach jedyną domenę
        planu Start i zablokował sobie wdrożenie produkcyjne.
        """
        subscribtion.plan_type = "start"
        subscribtion.save()

        zarejestruj_domene(tenant, "http://localhost:3000")
        zarejestruj_domene(tenant, "http://127.0.0.1:8000")

        assert WidgetDomain.objects.filter(tenant=tenant).count() == 0

    def test_brak_naglowka_nie_wywraca_zapytania(self, tenant, subscribtion):
        assert zarejestruj_domene(tenant, None) == ""


@pytest.mark.django_db
class TestLimituZCennika:
    @pytest.mark.parametrize("plan,limit", [("start", 1), ("grow", 3), ("pro", 10)])
    def test_limit_pochodzi_z_planu(self, tenant, subscribtion, plan, limit):
        subscribtion.plan_type = plan
        subscribtion.save()

        assert limit_domen(tenant) == limit

    def test_nieznany_plan_nie_jest_ograniczany(self, tenant, subscribtion):
        """Firma w okresie próbnym nie ma jeszcze subskrypcji — nie blokujemy jej."""
        subscribtion.plan_type = "Prymium"
        subscribtion.save()

        assert limit_domen(tenant) is None
        for numer in range(5):
            zarejestruj_domene(tenant, f"https://sklep{numer}.pl")

    def test_nasza_wlasna_domena_nie_zajmuje_limitu(self, tenant, subscribtion, settings):
        """
        Okno czatu dziala w ramce serwowanej spod naszego panelu, wiec
        zapytania z jej wnetrza niosa w naglowku Origin NASZ adres.

        Bez wykluczenia klient planu Start rejestrowal wlasna strone jako
        pierwsza witryne, a ramka widgetu probowala byc druga i dostawala
        odmowe -- widget tracil branding, a klient widzial w panelu nasza
        domene na liscie swoich witryn.
        """
        settings.FRONTEND_URL = "https://panel.agencjasm-art.pl"
        subscribtion.plan_type = "start"
        subscribtion.save()

        zarejestruj_domene(tenant, "https://sklep.pl")
        # Nie moze rzucic: to nie jest kolejna witryna klienta
        wynik = zarejestruj_domene(tenant, "https://panel.agencjasm-art.pl")

        assert wynik == ""
        assert WidgetDomain.objects.filter(tenant=tenant).count() == 1
        assert not WidgetDomain.objects.filter(host="panel.agencjasm-art.pl").exists()

    def test_wykluczenie_idzie_za_adresem_panelu(self, tenant, subscribtion, settings):
        # Adres bierzemy z FRONTEND_URL, wiec przeprowadzka panelu pod inny
        # adres przenosi wykluczenie razem z nim -- bez zmiany w kodzie.
        settings.FRONTEND_URL = "https://nowy-panel.example.com"
        subscribtion.plan_type = "start"
        subscribtion.save()

        assert zarejestruj_domene(tenant, "https://nowy-panel.example.com") == ""
        # Stary adres przestaje byc wykluczony -- to zwykla obca witryna
        assert zarejestruj_domene(tenant, "https://panel.agencjasm-art.pl") == "panel.agencjasm-art.pl"

    def test_cudza_domena_wciaz_liczy_sie_do_limitu(self, tenant, subscribtion, settings):
        # Wykluczenie ma dotyczyc WYLACZNIE naszego adresu. Gdyby rozlalo sie
        # szerzej, zniknelaby ochrona klucza API: kazdy moglby skopiowac klucz
        # ze strony klienta i zuzywac jego limit u siebie.
        settings.FRONTEND_URL = "https://panel.agencjasm-art.pl"
        subscribtion.plan_type = "start"
        subscribtion.save()
        zarejestruj_domene(tenant, "https://sklep.pl")

        with pytest.raises(PermissionDenied):
            zarejestruj_domene(tenant, "https://obca-strona.pl")

    def test_przekroczenie_limitu_zatrzymuje(self, tenant, subscribtion):
        subscribtion.plan_type = "start"
        subscribtion.save()
        zarejestruj_domene(tenant, "https://sklep.pl")

        with pytest.raises(PermissionDenied):
            zarejestruj_domene(tenant, "https://obca-strona.pl")

    def test_znana_witryna_dziala_mimo_przekroczonego_limitu(self, tenant, subscribtion):
        """
        Klient, który zszedł na niższy plan, ma więcej witryn niż przewiduje
        cennik. Wyłączenie działającego widgetu na stronie, za którą zapłacił
        w poprzednim miesiącu, byłoby dotkliwsze niż odczekanie do kolejnej
        nowej witryny.
        """
        subscribtion.plan_type = "grow"
        subscribtion.save()
        for numer in range(3):
            zarejestruj_domene(tenant, f"https://sklep{numer}.pl")

        subscribtion.plan_type = "start"
        subscribtion.save()

        assert zarejestruj_domene(tenant, "https://sklep0.pl") == "sklep0.pl"

    def test_limity_sa_osobne_dla_kazdej_firmy(self, tenant, subscribtion):
        from api.tests.factories import TenantFactory

        obcy = TenantFactory()
        subscribtion.plan_type = "start"
        subscribtion.save()
        zarejestruj_domene(tenant, "https://sklep.pl")

        # Obca firma nie ma subskrypcji, więc nie podlega limitowi
        zarejestruj_domene(obcy, "https://inny-sklep.pl")

        assert WidgetDomain.objects.filter(tenant=tenant).count() == 1
        assert WidgetDomain.objects.filter(tenant=obcy).count() == 1


@pytest.mark.django_db
class TestPrzezEndpointWidgetu:
    URL = "/api/widget-settings/"

    def test_widget_ze_strony_klienta_rejestruje_domene(self, tenant, subscribtion):
        subscribtion.plan_type = "grow"
        subscribtion.save()

        response = APIClient().get(
            self.URL, HTTP_X_API_KEY=str(tenant.api_key), HTTP_ORIGIN="https://sklep.pl"
        )

        assert response.status_code == 200
        assert WidgetDomain.objects.filter(tenant=tenant, host="sklep.pl").exists()

    def test_skradziony_klucz_na_obcej_stronie_zostaje_odrzucony(
        self, tenant, subscribtion
    ):
        """
        Sedno ochrony. Klucz API jest widoczny w kodzie strony klienta —
        bez limitu domen każdy mógł go skopiować i zużywać cudzy limit.
        """
        subscribtion.plan_type = "start"
        subscribtion.save()
        klient = APIClient()
        klient.get(self.URL, HTTP_X_API_KEY=str(tenant.api_key),
                   HTTP_ORIGIN="https://sklep.pl")

        response = klient.get(
            self.URL, HTTP_X_API_KEY=str(tenant.api_key),
            HTTP_ORIGIN="https://zlodziej.pl",
        )

        assert response.status_code == 403
        assert not WidgetDomain.objects.filter(host="zlodziej.pl").exists()

    def test_bez_naglowka_origin_widget_dziala(self, tenant, subscribtion):
        """
        Podgląd z panelu i wywołania spoza przeglądarki nie mają nagłówka —
        nie mogą przez to przestać działać.
        """
        response = APIClient().get(self.URL, HTTP_X_API_KEY=str(tenant.api_key))

        assert response.status_code == 200


@pytest.mark.django_db
class TestZarzadzaniaWPanelu:
    URL = "/api/widget-domains/"

    def wlasciciel(self, user, tenant, plan="grow"):
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

    def test_panel_widzi_witryny_i_limit(self, user, tenant, subscribtion):
        klient = self.wlasciciel(user, tenant, "grow")
        zarejestruj_domene(tenant, "https://sklep.pl")

        dane = klient.get(self.URL).json()

        assert dane["limit"] == 3
        assert dane["used"] == 1
        assert dane["domains"][0]["host"] == "sklep.pl"

    def test_usuniecie_zwalnia_miejsce(self, user, tenant, subscribtion):
        """
        Bez tego klient, który wyczerpał limit, trafiałby na ścianę bez wyjścia:
        widget na nowej witrynie nie działa, a starej nie da się usunąć.
        """
        klient = self.wlasciciel(user, tenant, "start")
        zarejestruj_domene(tenant, "https://stara.pl")
        domena = WidgetDomain.objects.get(tenant=tenant)

        assert klient.delete(f"{self.URL}{domena.id}/").status_code == 204

        zarejestruj_domene(tenant, "https://nowa.pl")
        assert WidgetDomain.objects.filter(tenant=tenant, host="nowa.pl").exists()

    def test_nie_da_sie_usunac_cudzej_witryny(self, user, tenant, subscribtion):
        from api.tests.factories import TenantFactory

        obcy = TenantFactory()
        zarejestruj_domene(obcy, "https://cudza.pl")
        cudza = WidgetDomain.objects.get(tenant=obcy)
        klient = self.wlasciciel(user, tenant)

        assert klient.delete(f"{self.URL}{cudza.id}/").status_code == 404
        assert WidgetDomain.objects.filter(id=cudza.id).exists()

    def test_nie_da_sie_dodac_witryny_recznie(self, user, tenant, subscribtion):
        """Wpis z palca i tak nie dałby dostępu witrynie, która o widget nie prosi."""
        klient = self.wlasciciel(user, tenant)

        assert klient.post(self.URL, {"host": "obca.pl"}, format="json").status_code == 405


@pytest.mark.django_db
class TestWartosciKtoreNieSaAdresem:
    """
    Wykryte na produkcji: w rejestrze jednego klienta siedziała "domena"
    o nazwie `null`. To nie adres, tylko to, co przeglądarka wysyła w nagłówku
    Origin ze stron w piaskownicy (iframe z atrybutem sandbox), z plików
    otwartych z dysku i z części przekierowań.

    Szkoda jest podwójna: w panelu wygląda to jak prawdziwa witryna, a przy
    tym zajmuje miejsce w limicie planu — klient Startu traci jedyną domenę
    na coś, czego nikt z zewnątrz nie odwiedzi.
    """

    @pytest.mark.parametrize("origin", [
        "null",          # iframe w piaskownicy, plik z dysku
        "undefined",     # przekazane z JS jako tekst
        "about:blank",   # pusta karta
        "http://intranet",   # host bez kropki — nie jest publiczną domeną
    ])
    def test_nie_trafiaja_do_rejestru(self, tenant, subscribtion, origin):
        assert zarejestruj_domene(tenant, origin) == ""
        assert WidgetDomain.objects.filter(tenant=tenant).count() == 0

    @pytest.mark.parametrize("origin", [
        "http://[::1]:3000",        # localhost po IPv6
        "http://192.168.1.10:8080", # sieć domowa/biurowa
        "http://10.0.0.5",          # sieć prywatna
        "http://app.localhost:3000",
        "http://drukarka.local",
    ])
    def test_praca_lokalna_nie_zjada_limitu(self, tenant, subscribtion, origin):
        """
        Wpis "[::1]" na liście hostów deweloperskich nigdy się nie dopasowywał:
        urlparse zwraca hostname bez nawiasów, czyli "::1". Praca na localhoście
        po IPv6 zabierała więc klientowi domenę z pakietu — dokładnie to, czemu
        ta lista miała zapobiegać.
        """
        subscribtion.plan_type = "start"
        subscribtion.save()

        assert zarejestruj_domene(tenant, origin) == ""
        assert WidgetDomain.objects.filter(tenant=tenant).count() == 0

    @pytest.mark.parametrize("origin,host", [
        ("https://sklep.pl", "sklep.pl"),
        ("https://www.sklep.pl:443", "sklep.pl"),
        ("https://moj.sklep.co.uk", "moj.sklep.co.uk"),
        ("https://8.8.8.8", "8.8.8.8"),
    ])
    def test_prawdziwe_witryny_nadal_sie_zapisuja(self, tenant, subscribtion, origin, host):
        """Filtr ma odcinać wartości, które adresem nie są — nie adresy."""
        assert zarejestruj_domene(tenant, origin) == host
        assert WidgetDomain.objects.filter(tenant=tenant, host=host).exists()

    def test_widget_dziala_mimo_odrzuconego_origin(self, tenant, subscribtion):
        """
        Odrzucenie wartości spoza rejestru nie może wyłączyć czatu: strona
        w piaskownicy to sytuacja normalna, nie nadużycie. Bez tego klient
        osadzający widget w ramce z atrybutem sandbox dostałby martwe okno.
        """
        klient = APIClient()
        klient.credentials(HTTP_X_API_KEY=str(tenant.api_key), HTTP_ORIGIN="null")

        odp = klient.get("/api/widget-settings/")

        assert odp.status_code == 200
        assert WidgetDomain.objects.filter(tenant=tenant).count() == 0
