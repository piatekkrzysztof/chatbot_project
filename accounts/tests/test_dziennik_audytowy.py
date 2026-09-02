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

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Tenant, WpisDziennika


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
    api = APIClient()
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
        api = APIClient()

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
