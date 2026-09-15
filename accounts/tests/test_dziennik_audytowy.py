"""
Dziennik audytowy.

Kategoria ryzyka: ROZLICZALNOŚĆ. Przy pierwszym sporze z klientem ("ktoś nam
skasował bazę wiedzy", "kto wyeksportował nasze rozmowy") bez dziennika nie ma
czym odpowiedzieć. Przy naruszeniu ochrony danych to jedyne źródło, z którego
da się odtworzyć przebieg zdarzeń, a każdy poważniejszy klient B2B pyta o to
w ankiecie bezpieczeństwa.

Zapis dzieje się w middleware, automatycznie. Testy pilnują trzech rzeczy:
że wpis powstaje i wskazuje właściwą osobę, że NIE powstaje tam, gdzie nie
powinien, i że dziennik nie potrafi wywrócić żądania, które się powiodło.
"""

from urllib.parse import parse_qs, urlsplit

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import get_resolver, reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts import totp
from accounts.models import DrugiSkladnik, InvitationToken, Tenant, WpisDziennika
from accounts.password_reset import reset_url
from documents.models import Document

HASLO = "tajne-haslo-2026"
PANEL = "https://panel.example.test"


@pytest.fixture
def firma(db):
    return Tenant.objects.create(name="Rowerownia Krakowska")


@pytest.fixture
def wlascicielka(db, django_user_model, firma):
    return django_user_model.objects.create_user(
        username="szef@rowerownia.pl",
        email="szef@rowerownia.pl",
        password="tajne-haslo-2026",
        tenant=firma,
        role="owner",
    )


@pytest.fixture
def klient(wlascicielka, firma):
    api = APIClient(HTTP_ORIGIN="https://panel.example.test")
    api.force_authenticate(user=wlascicielka)
    api.credentials(HTTP_X_API_KEY=str(firma.api_key))
    return api


@pytest.mark.django_db
class TestZapisu:
    def test_utworzenie_faq_zostawia_wpis_z_wlasciwa_osoba(self, klient, wlascicielka, firma):
        """
        Najważniejszy test w tym pliku.

        Sprawdza założenie, na którym stoi cały mechanizm: że po wykonaniu
        widoku użytkownik uwierzytelniony przez DRF jest widoczny także na
        żądaniu Django, do którego sięga middleware. Gdyby nie był, wpisy
        powstawałyby - ale wszystkie anonimowe, czyli bezwartościowe.
        """
        klient.post(
            reverse("faq-list"),
            {"question": "Jakie macie godziny?", "answer": "Pon-pt 9-18."},
            format="json",
        )

        wpis = WpisDziennika.objects.latest("czas")
        assert wpis.uzytkownik_id == wlascicielka.id
        assert wpis.nazwa_uzytkownika == "szef@rowerownia.pl"
        assert wpis.tenant_id == firma.id
        assert wpis.metoda == "POST"

    def test_wpis_niesie_wynik_zadania(self, klient):
        # Bez statusu nie wiadomo, czy próba się powiodła - a "ktoś próbował
        # skasować i dostał odmowę" to inna informacja niż "ktoś skasował".
        klient.post(reverse("faq-list"), {"question": "", "answer": ""}, format="json")

        wpis = WpisDziennika.objects.latest("czas")
        assert wpis.status == 400

    def test_odczyty_nie_zasmiecaja_dziennika(self, klient):
        # GET-y to zwykłe przeglądanie panelu. Zapisywanie ich zamieniłoby
        # dziennik w log dostępu i utopiło w nim to, po co powstał.
        klient.get(reverse("faq-list"))

        assert not WpisDziennika.objects.exists()

    def test_ruch_widgetu_nie_trafia_do_dziennika(self, klient, firma):
        # Widget to odwiedzający stronę klienta, a nie działania w panelu.
        # Przy kilku tysiącach rozmów dziennie dziennik przestałby się nadawać
        # do czytania.
        klient.post(
            reverse("widget-chat-stream"),
            {"message": "Dzien dobry"},
            format="json",
        )

        assert not WpisDziennika.objects.filter(sciezka__startswith="/api/widget/").exists()


@pytest.mark.django_db
class TestOdpornosci:
    def test_awaria_dziennika_nie_wywraca_zapisanej_zmiany(self, klient, mocker):
        """
        Zapisana zmiana bez wpisu to luka w dzienniku. Odrzucone żądanie
        z powodu awarii dziennika to utrata pracy użytkownika. Z dwojga złego
        wybieramy lukę - ale zostawiamy po niej ślad w logu.
        """
        mocker.patch(
            "accounts.models.WpisDziennika.objects.create",
            side_effect=RuntimeError("baza dziennika niedostepna"),
        )

        odpowiedz = klient.post(
            reverse("faq-list"),
            {"question": "Jakie macie godziny?", "answer": "Pon-pt 9-18."},
            format="json",
        )

        assert odpowiedz.status_code == 201

    def test_nieudane_logowanie_tez_zostawia_slad(self, db):
        # Zdarzenie sprzed rozpoznania firmy: nie ma tenanta ani użytkownika,
        # ale jest adres i wynik. To jest dokładnie ten wpis, którego szuka
        # się po włamaniu.
        api = APIClient(HTTP_ORIGIN="https://panel.example.test")

        api.post(
            reverse("login"),
            {"username": "nikt@nigdzie.pl", "password": "zle"},
            format="json",
            REMOTE_ADDR="203.0.113.9",
        )

        wpis = WpisDziennika.objects.latest("czas")
        assert wpis.sciezka == "/api/accounts/login/"
        assert wpis.status == 401
        assert wpis.uzytkownik is None
        assert wpis.adres_ip == "203.0.113.9"


@pytest.mark.django_db
class TestTrwalosci:
    def test_wpis_przezywa_usuniecie_konta(self, klient, wlascicielka):
        """
        Gdyby wpisy ginęły razem z kontem, wystarczyłoby skasować użytkownika,
        żeby zniknął zapis jego działań - czyli dziennik znikałby dokładnie
        wtedy, gdy jest najbardziej potrzebny.
        """
        klient.post(
            reverse("faq-list"),
            {"question": "Jakie macie godziny?", "answer": "Pon-pt 9-18."},
            format="json",
        )
        ile_przed = WpisDziennika.objects.count()

        wlascicielka.delete()

        assert WpisDziennika.objects.count() == ile_przed
        wpis = WpisDziennika.objects.latest("czas")
        assert wpis.uzytkownik is None
        # Kopia tekstowa zostaje, więc wpis nadal mówi, kto to był.
        assert wpis.nazwa_uzytkownika == "szef@rowerownia.pl"


@pytest.mark.django_db
class TestOdczytuPrzezWlasciciela:
    """
    Dziennik, do którego zagląda wyłącznie dostawca, jest bezużyteczny dla
    klienta - to jego audytor pyta, kto skasował dane.
    """

    URL = "/api/accounts/dziennik/"

    def test_wlascicielka_widzi_wpisy_swojej_firmy(self, klient):
        klient.post(
            reverse("faq-list"),
            {"question": "Jakie macie godziny?", "answer": "Pon-pt 9-18."},
            format="json",
        )

        odpowiedz = klient.get(self.URL)

        assert odpowiedz.status_code == 200
        assert odpowiedz.data["count"] >= 1

    def test_wpisy_innej_firmy_sa_niewidoczne(self, klient, db, django_user_model):
        """
        Najważniejszy test w tej klasie. Dziennik zbiera działania wszystkich
        najemców w jednej tabeli, więc pomyłka w filtrowaniu pokazałaby
        klientowi, co robią inni klienci - i to akurat w miejscu, które ma
        służyć za dowód rozdzielenia danych.
        """
        obca_firma = Tenant.objects.create(name="Obca firma")
        obcy = django_user_model.objects.create_user(
            username="ktos@obcej.pl",
            email="ktos@obcej.pl",
            password="tajne-haslo-2026",
            tenant=obca_firma,
            role="owner",
        )
        obcy_klient = APIClient()
        obcy_klient.force_authenticate(user=obcy)
        obcy_klient.credentials(HTTP_X_API_KEY=str(obca_firma.api_key))
        obcy_klient.post(
            reverse("faq-list"),
            {"question": "Pytanie obcej firmy", "answer": "Odpowiedz"},
            format="json",
        )

        odpowiedz = klient.get(self.URL)

        sciezki = [wpis["nazwa_uzytkownika"] for wpis in odpowiedz.data["results"]]
        assert "ktos@obcej.pl" not in sciezki

    def test_pracownik_nie_ma_dostepu(self, klient, wlascicielka):
        # Dziennik pokazuje działania wszystkich osób w firmie, więc jego
        # odczyt jest uprawnieniem nadzorczym, a nie roboczym.
        wlascicielka.role = "employee"
        wlascicielka.save()

        assert klient.get(self.URL).status_code == 403

    def test_dziennika_nie_da_sie_zmienic_przez_api(self, klient):
        # Zapis, który da się poprawić po fakcie, nie jest dowodem niczego.
        assert klient.post(self.URL, {}, format="json").status_code == 405
        assert klient.delete(self.URL).status_code == 405


def wpis_dla(sciezka):
    return WpisDziennika.objects.get(sciezka=sciezka)


@pytest.mark.django_db
class TestOdczytowWynoszacychDane:
    """
    Model dziennika obiecuje odpowiedź na pytanie "kto wyeksportował nasze
    rozmowy", a ekran dziennika wymienia eksporty wśród zapisywanych zdarzeń.
    Zapisywane były jednak tylko żądania zmieniające dane, a eksport rozmów
    i pobranie pliku to GET - czyli akurat te zdarzenia, o które pyta się po
    incydencie, nie zostawiały śladu.
    """

    def test_eksport_rozmow_zostawia_wpis(self, klient, wlascicielka, firma):
        odpowiedz = klient.get(reverse("chat-export-csv"))
        b"".join(odpowiedz.streaming_content)

        assert odpowiedz.status_code == 200
        wpis = wpis_dla("/api/chat/export/")
        assert wpis.metoda == "GET"
        assert wpis.uzytkownik == wlascicielka
        assert wpis.tenant == firma

    def test_odmowa_eksportu_tez_zostawia_slad(self, klient, wlascicielka):
        # Próba wyniesienia danych bez uprawnień mówi po incydencie więcej
        # niż udany eksport osoby, która miała do tego prawo.
        wlascicielka.role = "viewer"
        wlascicielka.save()

        assert klient.get(reverse("chat-export-csv")).status_code == 403
        assert wpis_dla("/api/chat/export/").status == 403

    def test_pobranie_dokumentu_zostawia_wpis(self, klient, firma, settings, tmp_path):
        settings.PRIVATE_MEDIA_ROOT = tmp_path / "private"
        dokument = Document.objects.create(
            tenant=firma, name="cennik.txt", file=SimpleUploadedFile("cennik.txt", b"CENNIK")
        )

        odpowiedz = klient.get(reverse("documents-download", args=[dokument.pk]))

        assert odpowiedz.status_code == 200
        wpis = wpis_dla(f"/api/documents/{dokument.pk}/download/")
        assert wpis.metoda == "GET"
        assert wpis.tenant == firma
        # Zamknięcie odpowiedzi kończy żądanie i zamyka połączenie z bazą,
        # więc dopiero po sprawdzeniu wpisu.
        odpowiedz.close()

    def test_zwykly_podglad_dokumentu_nie_trafia_do_dziennika(self, klient, firma):
        # Zapis odczytów jest wąski celowo: wpis przy każdym wejściu na ekran
        # utopiłby wynoszenie danych w zwykłym przeglądaniu panelu.
        dokument = Document.objects.create(tenant=firma, name="cennik.txt", content="CENNIK")

        assert klient.get(reverse("document-detail", args=[dokument.pk])).status_code == 200
        assert not WpisDziennika.objects.exists()

    def test_nazwy_zapisywanych_odczytow_istnieja(self):
        # Odczyt jest rozpoznawany po nazwie trasy. Zmiana nazwy bez zmiany
        # listy wyłączyłaby zapis po cichu - ten test to zatrzymuje.
        from accounts.middleware import ODCZYTY_W_DZIENNIKU

        nazwy = get_resolver().reverse_dict
        assert ODCZYTY_W_DZIENNIKU
        for nazwa in ODCZYTY_W_DZIENNIKU:
            assert nazwa in nazwy


@pytest.mark.django_db
class TestAutoraZdarzenDostepu:
    """
    Logowanie, wylogowanie, założenie konta, przyjęcie zaproszenia i ustawienie
    nowego hasła dzieją się, zanim żądanie ma zalogowanego użytkownika. Wpis
    powstawał bez osoby i bez firmy, więc właściciel go nie widział - choć
    ekran dziennika obiecuje właśnie logowania. Po przejęciu konta pracownika
    to pierwszy wpis, którego się szuka.
    """

    def zaloguj(self, api, uzytkownik, haslo=HASLO):
        return api.post(
            reverse("login"),
            {"username": uzytkownik.username, "password": haslo},
            format="json",
            REMOTE_ADDR="203.0.113.7",
        )

    def test_udane_logowanie_wskazuje_osobe_i_firme(self, klient, wlascicielka, firma):
        odpowiedz = self.zaloguj(APIClient(HTTP_ORIGIN=PANEL), wlascicielka)

        assert odpowiedz.status_code == 200
        wpis = wpis_dla("/api/accounts/login/")
        assert (wpis.uzytkownik, wpis.tenant) == (wlascicielka, firma)
        assert wpis.nazwa_uzytkownika == wlascicielka.username
        assert wpis.adres_ip == "203.0.113.7"
        widoczne = klient.get("/api/accounts/dziennik/").data["results"]
        assert "/api/accounts/login/" in [w["sciezka"] for w in widoczne]

    def test_zle_haslo_do_istniejacego_konta_zostaje_anonimowe(self, wlascicielka):
        # Przypisanie nieudanej próby do konta pozwalałoby każdemu dopisywać
        # wpisy do dziennika cudzej firmy, znając sam adres e-mail.
        odpowiedz = self.zaloguj(APIClient(HTTP_ORIGIN=PANEL), wlascicielka, haslo="zle")

        assert odpowiedz.status_code == 401
        wpis = wpis_dla("/api/accounts/login/")
        assert (wpis.uzytkownik, wpis.tenant) == (None, None)

    def test_logowanie_dwuetapowe_wskazuje_osobe_w_obu_krokach(self, wlascicielka, firma):
        skladnik = DrugiSkladnik.objects.create(
            uzytkownik=wlascicielka, sekret=totp.nowy_sekret(), potwierdzony_od=timezone.now()
        )
        api = APIClient(HTTP_ORIGIN=PANEL)
        bilet = self.zaloguj(api, wlascicielka).data["bilet"]

        odpowiedz = api.post(
            reverse("login-2fa"),
            {"bilet": bilet, "kod": totp.kod(skladnik.sekret)},
            format="json",
        )

        assert odpowiedz.status_code == 200
        for sciezka in ("/api/accounts/login/", "/api/accounts/login/2fa/"):
            wpis = wpis_dla(sciezka)
            assert (wpis.uzytkownik, wpis.tenant) == (wlascicielka, firma)

    def test_bledny_kod_drugiego_skladnika_zostaje_anonimowy(self, wlascicielka):
        DrugiSkladnik.objects.create(
            uzytkownik=wlascicielka, sekret=totp.nowy_sekret(), potwierdzony_od=timezone.now()
        )
        api = APIClient(HTTP_ORIGIN=PANEL)
        bilet = self.zaloguj(api, wlascicielka).data["bilet"]

        odpowiedz = api.post(reverse("login-2fa"), {"bilet": bilet, "kod": "000000"}, format="json")

        assert odpowiedz.status_code == 400
        assert wpis_dla("/api/accounts/login/2fa/").uzytkownik is None

    def test_wylogowanie_wskazuje_osobe(self, wlascicielka, firma):
        api = APIClient(HTTP_ORIGIN=PANEL)
        assert self.zaloguj(api, wlascicielka).status_code == 200

        odpowiedz = api.post(reverse("logout"))

        assert odpowiedz.status_code == 204
        wpis = wpis_dla("/api/accounts/logout/")
        assert (wpis.uzytkownik, wpis.tenant) == (wlascicielka, firma)

    def test_przyjecie_zaproszenia_wskazuje_nowa_osobe(self, firma):
        zaproszenie = InvitationToken.objects.create(
            tenant=firma, email="nowa@rowerownia.pl", role="employee", duration="1d", max_users=1
        )

        odpowiedz = APIClient().post(
            "/api/accounts/accept-invite/",
            {
                "token": str(zaproszenie.token),
                "username": "nowa",
                "email": "nowa@rowerownia.pl",
                "password": "TajneHaslo123",
            },
            format="json",
        )

        assert odpowiedz.status_code == 201
        wpis = wpis_dla("/api/accounts/accept-invite/")
        assert wpis.nazwa_uzytkownika == "nowa"
        assert wpis.tenant == firma

    def test_potwierdzenie_rejestracji_wskazuje_nowa_firme(self):
        from api.tests.signup_helpers import latest_token
        from api.tests.test_registration_security import PASSWORD, registration

        dane = registration()
        dane.pop("password", None)
        assert APIClient().post("/api/accounts/register/", dane).status_code == 202

        odpowiedz = APIClient().post(
            "/api/accounts/registration/activate/",
            {"token": latest_token(), "password": PASSWORD},
        )

        assert odpowiedz.status_code == 201
        wpis = wpis_dla("/api/accounts/registration/activate/")
        assert wpis.uzytkownik is not None
        assert wpis.tenant == wpis.uzytkownik.tenant

    def test_nowe_haslo_z_linku_wskazuje_osobe(self, wlascicielka, firma):
        dowod = {
            nazwa: wartosci[0]
            for nazwa, wartosci in parse_qs(urlsplit(reset_url(wlascicielka)).fragment).items()
        }

        odpowiedz = APIClient(HTTP_ORIGIN=PANEL).post(
            "/api/accounts/password-reset/confirm/",
            {**dowod, "password": "Niezalezne-haslo!739"},
            format="json",
        )

        assert odpowiedz.status_code == 200
        wpis = wpis_dla("/api/accounts/password-reset/confirm/")
        assert (wpis.uzytkownik, wpis.tenant) == (wlascicielka, firma)
