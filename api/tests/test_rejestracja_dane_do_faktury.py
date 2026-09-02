"""
Rejestracja zbierająca dane do faktury i umowy.

Kategoria ryzyka: PIENIĄDZE i FORMALNOŚCI. Bez tych danych nie da się wystawić
faktury ani podpisać umowy powierzenia - a dopytywanie o nie dopiero przy
płatności zatrzymuje klienta w najgorszym możliwym miejscu, tuż przed
zapłaceniem.

Testy pilnują obu stron: że komplet danych zakłada konto razem z danymi
rozliczeniowymi, ORAZ że braki i literówki zatrzymują rejestrację TAM, gdzie
da się je poprawić - a nie kilka tygodni później, u księgowej klienta.
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import CustomUser, DaneRozliczeniowe, Tenant

URL = "/api/accounts/register/"

KOMPLET = {
    "imie": "Anna",
    "nazwisko": "Nowak",
    "company_name": "Rowerownia",
    "email": "anna@rowerownia.pl",
    "password": "bardzoTajneHaslo123",
    "nazwa_do_faktury": "Rowerownia Krakowska Anna Nowak",
    "nip": "526-025-02-74",
    "ulica": "Krakowska 12/3",
    "kod_pocztowy": "31-000",
    "miasto": "Kraków",
}


def zarejestruj(**zmiany):
    dane = {**KOMPLET, **zmiany}
    for klucz, wartosc in list(dane.items()):
        if wartosc is None:
            dane.pop(klucz)
    return APIClient().post(URL, dane, format="json")


@pytest.mark.django_db
class TestKompletnychDanych:
    def test_konto_powstaje_razem_z_danymi_rozliczeniowymi(self):
        odpowiedz = zarejestruj()

        assert odpowiedz.status_code == 201
        dane = DaneRozliczeniowe.objects.get()
        assert dane.nazwa == "Rowerownia Krakowska Anna Nowak"
        assert dane.ulica == "Krakowska 12/3"
        assert dane.miasto == "Kraków"

    def test_imie_i_nazwisko_trafiaja_do_konta(self):
        # Do umowy, i po to, żeby wiadomości nie zaczynały się od
        # "Szanowni Państwo" w korespondencji z jedną osobą.
        zarejestruj()

        uzytkownik = CustomUser.objects.get(email="anna@rowerownia.pl")
        assert uzytkownik.first_name == "Anna"
        assert uzytkownik.last_name == "Nowak"

    def test_nazwa_robocza_i_nazwa_na_fakturze_sa_osobne(self):
        """
        W panelu i w widgecie ma stać krótka nazwa, na fakturze pełna z rejestru.
        Sklejenie ich w jedno pole znaczyłoby, że klient wybiera między
        czytelnym widgetem a poprawną fakturą.
        """
        zarejestruj()

        assert Tenant.objects.get().name == "Rowerownia"
        assert DaneRozliczeniowe.objects.get().nazwa == "Rowerownia Krakowska Anna Nowak"

    def test_nip_zapisuje_sie_znormalizowany(self):
        # Ten sam numer wpisany z myślnikami i bez musi trafić do bazy w jednej
        # postaci - inaczej to samo przedsiębiorstwo wygląda na dwa różne.
        zarejestruj(nip="526-025-02-74")

        assert DaneRozliczeniowe.objects.get().nip == "5260250274"

    def test_kraj_domyslnie_polska(self):
        zarejestruj()

        assert DaneRozliczeniowe.objects.get().kraj == "PL"


@pytest.mark.django_db
class TestBrakowICzegosNiepoprawnego:
    @pytest.mark.parametrize("pole", ["imie", "nazwisko", "ulica", "kod_pocztowy", "miasto"])
    def test_brak_wymaganego_pola_zatrzymuje_rejestracje(self, pole):
        odpowiedz = zarejestruj(**{pole: None})

        assert odpowiedz.status_code == 400
        assert pole in odpowiedz.data

    def test_zly_nip_zatrzymuje_rejestracje_z_czytelnym_powodem(self):
        """
        Najważniejszy test w tym pliku.

        NIP z przestawionymi cyframi wygląda jak NIP i przechodzi przez każdy
        formularz, który sprawdza tylko długość. Wychodzi dopiero na fakturze -
        u księgowej klienta, kilka tygodni później, gdy trzeba wystawić korektę,
        a klient nie odliczy podatku.
        """
        odpowiedz = zarejestruj(nip="5260250247")

        assert odpowiedz.status_code == 400
        # Rdzen slowa, nie cala frazna - komunikat odmienia sie przez przypadki
        assert "kontroln" in str(odpowiedz.data["nip"]).lower()

    def test_zly_nip_nie_zostawia_polowicznego_konta(self):
        # Konto bez danych rozliczeniowych albo dane bez konta byłyby gorsze
        # niż odrzucenie: klient nie wiedziałby, czy się zarejestrował.
        zarejestruj(nip="5260250247")

        assert not CustomUser.objects.exists()
        assert not Tenant.objects.exists()
        assert not DaneRozliczeniowe.objects.exists()


@pytest.mark.django_db
class TestKlientaBezNIP:
    def test_osoba_prywatna_rejestruje_sie_bez_nip(self):
        # Klientem bywa osoba prywatna albo działalność nierejestrowana.
        # Wymuszanie NIP-u odcinałoby ich całkowicie.
        odpowiedz = zarejestruj(nip=None)

        assert odpowiedz.status_code == 201
        assert DaneRozliczeniowe.objects.get().nip == ""

    def test_puste_pole_nip_tez_przechodzi(self):
        # Formularz wysyła puste pole jako pusty napis, nie jako brak klucza.
        odpowiedz = zarejestruj(nip="")

        assert odpowiedz.status_code == 201

    def test_bez_nazwy_na_fakturze_bierzemy_robocza(self):
        # Lepsza niż pusta - klient poprawi ją w ustawieniach, gdy będzie
        # trzeba, a faktura da się wystawić od pierwszego dnia.
        zarejestruj(nazwa_do_faktury=None)

        assert DaneRozliczeniowe.objects.get().nazwa == "Rowerownia"
