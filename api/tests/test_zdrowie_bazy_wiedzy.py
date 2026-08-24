"""
Zdrowie bazy wiedzy i poczty na stronie Stan.

Powstało z przypadku, który trwał tygodniami i nie było go po czym poznać:
strona główna klienta miała w bazie 257 znaków z 10 037 widocznych na stronie,
a panel pokazywał zielone "gotowe". Status mówił prawdę — dokument BYŁ
przetworzony. Tyle że pusty, i nic tego nie zdradzało.

Druga rzecz to poczta: wszystkie sprawdzenia, które zbudowaliśmy, siedziały
w konsoli. Klient nie ma jak zobaczyć, że jego powiadomienia nie wychodzą —
dowie się, przegapiając zapytanie.
"""
import pytest
from rest_framework.test import APIClient

from accounts.models import CustomUser, Tenant
from api.views.diagnostyka_zadan import _zdrowie_bazy_wiedzy, _zdrowie_poczty
from chat.models import ContactRequest
from documents.models import Document, DocumentChunk

URL = "/api/diagnostyka/zadania/"


@pytest.fixture
def firma(db):
    return Tenant.objects.create(name="Sm-art", owner_email="wlasciciel@firma.pl")


def dokument(tenant, nazwa, tresc="tresc dokumentu", widocznych=None, fragmenty=1, **kw):
    dok = Document.objects.create(
        tenant=tenant, name=nazwa, content=tresc, processed=True,
        znakow_na_stronie=widocznych, **kw,
    )
    for numer in range(fragmenty):
        DocumentChunk.objects.create(
            document=dok, content=f"fragment {numer}", embedding=[0.01] * 1536
        )
    return dok


@pytest.mark.django_db
class TestBazyWiedzy:
    def test_dokument_bez_fragmentow_to_awaria(self, firma):
        """
        Tresc jest, wektory sie nie policzyly — bot tego nie zna, mimo ze
        w bazie wiedzy pozycja wyglada na gotowa. Bez tego sygnalu nie ma
        jak tego zobaczyc inaczej niz przez konsole.
        """
        dokument(firma, "Cennik.pdf", fragmenty=0)

        wynik = _zdrowie_bazy_wiedzy(firma)

        assert wynik["wniosek"] == "nie-dziala"
        assert wynik["bez_fragmentow"] == ["Cennik.pdf"]

    def test_niepelna_podstrona_to_ostrzezenie(self, firma):
        """Dokladnie przypadek strony glownej: 257 znakow z 10 037."""
        dokument(firma, "https://firma.pl", tresc="x" * 257, widocznych=10037)

        wynik = _zdrowie_bazy_wiedzy(firma)

        assert wynik["wniosek"] == "ostrzezenie"
        assert wynik["niepelne"] == [{"nazwa": "https://firma.pl", "udzial_procent": 3}]

    def test_dobrze_pobrana_strona_nie_alarmuje(self, firma):
        """Cennik wychodzil w 73% i to jest w porzadku — prog nie moze
        krzyczec przy stronach, ktore po prostu maja duzo nawigacji."""
        dokument(firma, "https://firma.pl/cennik", tresc="x" * 10155, widocznych=13964)

        assert _zdrowie_bazy_wiedzy(firma)["wniosek"] == "dziala"

    def test_wgrany_plik_nie_jest_oceniany(self, firma):
        """Nie ma strony, z ktora mozna go porownac — brak mianownika znaczy
        brak orzeczenia, nie ostrzezenie."""
        dokument(firma, "Cennik.pdf", tresc="x" * 50, widocznych=None)

        assert _zdrowie_bazy_wiedzy(firma)["wniosek"] == "dziala"

    def test_dokument_wylaczony_z_wyszukiwania_nie_liczy_sie(self, firma):
        """Klient swiadomie go pominal — ostrzeganie o nim byloby halasem."""
        dokument(firma, "https://firma.pl/kontakt", tresc="x" * 50,
                 widocznych=5000, uzywaj_w_wyszukiwaniu=False)

        assert _zdrowie_bazy_wiedzy(firma)["wniosek"] == "brak-danych"

    def test_awaria_ma_pierwszenstwo_przed_ostrzezeniem(self, firma):
        """Brak fragmentow znaczy, ze bot czegos NIE ZNA. Niepelna strona
        znaczy, ze zna mniej. Pierwsze jest pilniejsze."""
        dokument(firma, "Bez wektorow.pdf", fragmenty=0)
        dokument(firma, "https://firma.pl", tresc="x" * 100, widocznych=10000)

        assert _zdrowie_bazy_wiedzy(firma)["wniosek"] == "nie-dziala"

    def test_pusta_baza_jest_nazwana_wprost(self, firma):
        assert _zdrowie_bazy_wiedzy(firma)["wniosek"] == "brak-danych"

    def test_nie_widac_dokumentow_obcej_firmy(self, firma, db):
        obca = Tenant.objects.create(name="Obca", owner_email="o@b.pl")
        dokument(obca, "Cudzy sekret.pdf", fragmenty=0)

        assert _zdrowie_bazy_wiedzy(firma)["wniosek"] == "brak-danych"
        assert _zdrowie_bazy_wiedzy(firma)["bez_fragmentow"] == []

    def test_lista_jest_przycieta(self, firma):
        """Sto zepsutych dokumentow to nadal jeden problem do rozwiazania."""
        for numer in range(15):
            dokument(firma, f"Dokument {numer}.pdf", fragmenty=0)

        wynik = _zdrowie_bazy_wiedzy(firma)

        assert wynik["dokumentow"] == 15
        assert len(wynik["bez_fragmentow"]) == 10


@pytest.mark.django_db
class TestPoczty:
    def test_brak_adresu_to_ostrzezenie(self, db):
        pusta = Tenant.objects.create(name="Bez adresu", owner_email="")

        wynik = _zdrowie_poczty(pusta)

        assert wynik["wniosek"] == "ostrzezenie"
        assert "po zalogowaniu" in wynik["opis"]

    def test_nieudane_powiadomienia_sa_widoczne(self, firma):
        """Klient nie dowie sie o zepsutej poczcie inaczej niz przegapiajac
        zapytanie."""
        ContactRequest.objects.create(
            tenant=firma, contact="jan@klient.pl",
            blad_powiadomienia="SMTPSenderRefused: 501",
        )

        wynik = _zdrowie_poczty(firma)

        assert wynik["wniosek"] == "ostrzezenie"
        assert "po stronie poczty" in wynik["opis"]

    def test_wszystko_dziala_podaje_adres(self, firma):
        wynik = _zdrowie_poczty(firma)

        assert wynik["wniosek"] == "dziala"
        assert "wlasciciel@firma.pl" in wynik["opis"]

    def test_bledna_konfiguracja_to_awaria(self, firma, settings):
        settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
        settings.DEFAULT_FROM_EMAIL = "powiadomienia@agencjasm_art.pl"
        settings.EMAIL_HOST = "smtp.resend.com"
        settings.EMAIL_HOST_PASSWORD = "klucz"

        wynik = _zdrowie_poczty(firma)

        assert wynik["wniosek"] == "nie-dziala"
        assert "DEFAULT_FROM_EMAIL" in wynik["opis"]

    def test_nie_widac_zapytan_obcej_firmy(self, firma, db):
        obca = Tenant.objects.create(name="Obca", owner_email="o@b.pl")
        ContactRequest.objects.create(
            tenant=obca, contact="x@y.pl", blad_powiadomienia="awaria u obcych",
        )

        assert _zdrowie_poczty(firma)["wniosek"] == "dziala"


@pytest.mark.django_db
class TestEndpointu:
    def test_panel_dostaje_obie_sekcje(self, firma):
        dokument(firma, "https://firma.pl", tresc="x" * 257, widocznych=10037)
        uzytkownik = CustomUser.objects.create_user(
            username="wl", email="wl@firma.pl", password="x", tenant=firma, role="owner",
        )
        klient = APIClient()
        klient.force_authenticate(user=uzytkownik)
        klient.credentials(HTTP_X_API_KEY=str(firma.api_key))

        odp = klient.get(URL)

        assert odp.status_code == 200
        dane = odp.json()
        assert dane["baza_wiedzy"]["wniosek"] == "ostrzezenie"
        assert dane["poczta"]["wniosek"] == "dziala"

    def test_poziom_ogolny_nie_zmienia_sie_przez_niepelna_strone(self, firma):
        """
        Niepelna podstrona nie znaczy, ze system nie dziala — znaczy, ze wiedza
        jest ubozsza, niz sie wydaje. Wciagniecie tego do werdyktu o zapleczu
        zamienialoby ostrzezenie o tresci w alarm o awarii.
        """
        dokument(firma, "https://firma.pl", tresc="x" * 257, widocznych=10037)
        uzytkownik = CustomUser.objects.create_user(
            username="wl2", email="wl2@firma.pl", password="x", tenant=firma, role="owner",
        )
        klient = APIClient()
        klient.force_authenticate(user=uzytkownik)
        klient.credentials(HTTP_X_API_KEY=str(firma.api_key))

        dane = klient.get(URL).json()

        assert dane["baza_wiedzy"]["wniosek"] == "ostrzezenie"
        assert "baza_wiedzy" not in str(dane["werdykt"])


@pytest.mark.django_db
class TestCennika:
    def test_publiczny_cennik_pokazuje_odswiezanie_tresci(self):
        """
        Realna roznica miedzy planami (Grow co 7 dni, Pro codziennie), ktora
        od niedawna faktycznie dziala — a klient jej nie widzial, bo endpoint
        cennika jej nie zwracal.
        """
        odp = APIClient().get("/api/billing/cennik/")

        assert odp.status_code == 200
        plany = {p["code"]: p for p in odp.json()["plans"]}
        assert plany["start"]["recrawl_days"] is None
        assert plany["grow"]["recrawl_days"] == 7
        assert plany["pro"]["recrawl_days"] == 1
