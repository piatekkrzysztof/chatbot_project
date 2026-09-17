"""
Koszt krańcowy klienta: arytmetyka, na której stoi cennik.

Kategoria ryzyka: DECYZJA CENOWA NA ZŁEJ LICZBIE. Ten pomiar ma odpowiedzieć,
czy 149 zł za 2 000 wiadomości ma sens. Pomyłka w mnożeniu nie wywraca niczego
w działaniu - wywraca decyzję, którą podejmuje się raz i żyje z nią rok.

Sam ruch HTTP do OpenAI nie jest tu testowany, bo go nie ma: komenda czyta
logi. Testujemy część, która z logów robi liczbę, oraz to, czego do tej liczby
NIE wolno wliczyć.
"""

import io

import pytest
from django.core.management import CommandError, call_command

from accounts.plans import PLANS, START
from chat.management.commands.zmierz_koszt_klienta import (
    koszt_bazy_wiedzy,
    koszt_wiadomosci,
    marza_planu,
    rozklad_tokenow,
)

CENY = {
    "wejscie": 0.15,
    "wyjscie": 0.60,
    "embedding": 0.02,
    "kurs": 4.0,
    "pytanie_tokenow": 0,
}


class TestRozkladu:
    def test_import_csv_nie_zanizadlaczy_sredniej(self):
        # Import historii zapisuje log z zerem tokenów: model nigdy tej
        # wiadomości nie wygenerował. Wliczony do średniej obniżałby koszt
        # wiadomości, za którą naprawdę płacimy.
        wpisy = [
            ("prompt", "odpowiedz", 1000),
            ("z csv", "z csv", 0),
            ("z csv", "z csv", 0),
        ]

        wynik = rozklad_tokenow(wpisy)

        assert wynik["wiadomosci"] == 1
        assert wynik["na_wiadomosc"] == 1000

    def test_wpis_bez_odpowiedzi_nie_liczy_sie(self):
        # Przerwana rozmowa: pytanie poszło, odpowiedź nie wróciła.
        assert rozklad_tokenow([("prompt", "", 500)])["wiadomosci"] == 0
        assert rozklad_tokenow([("prompt", None, 500)])["wiadomosci"] == 0

    def test_udzial_wyjscia_z_dlugosci_tekstow(self):
        # Trzy razy dłuższy prompt niż odpowiedź: wyjście to jedna czwarta.
        wynik = rozklad_tokenow([("x" * 300, "y" * 100, 400)])

        assert wynik["udzial_wyjscia"] == pytest.approx(0.25)

    def test_brak_danych_nie_wywraca_sie(self):
        wynik = rozklad_tokenow([])

        assert wynik == {
            "wiadomosci": 0,
            "tokenow": 0,
            "udzial_wyjscia": 0.0,
            "na_wiadomosc": 0.0,
        }


class TestKosztu:
    def test_wyjscie_liczone_drozej_niz_wejscie(self):
        # 1000 tokenów, z czego jedna czwarta to wyjście:
        # 750 * 0,15 + 250 * 0,60 = 112,5 + 150 = 262,5 USD za milion,
        # czyli 0,0002625 USD, po kursie 4 -> 0,00105 zł.
        rozklad = {"na_wiadomosc": 1000, "udzial_wyjscia": 0.25}

        assert koszt_wiadomosci(rozklad, CENY) == pytest.approx(0.00105)

    def test_sam_podzial_zmienia_wynik(self):
        # Gdyby wszystko policzyć po stawce wejścia, wynik byłby zaniżony -
        # dlatego udział wyjścia w ogóle szacujemy, zamiast go pominąć.
        tanszy = koszt_wiadomosci({"na_wiadomosc": 1000, "udzial_wyjscia": 0.0}, CENY)
        drozszy = koszt_wiadomosci({"na_wiadomosc": 1000, "udzial_wyjscia": 1.0}, CENY)

        assert drozszy == pytest.approx(4 * tanszy)

    def test_wektor_pytania_dolicza_sie_do_kazdej_wiadomosci(self):
        bez = koszt_wiadomosci({"na_wiadomosc": 1000, "udzial_wyjscia": 0.5}, CENY)
        z_pytaniem = koszt_wiadomosci(
            {"na_wiadomosc": 1000, "udzial_wyjscia": 0.5}, {**CENY, "pytanie_tokenow": 20}
        )

        assert z_pytaniem > bez

    def test_koszt_wektorow_calej_bazy_wiedzy(self):
        # 3 mln znaków to milion tokenów przy trzech znakach na token:
        # 0,02 USD, po kursie 4 -> 0,08 zł.
        assert koszt_bazy_wiedzy(3_000_000, CENY) == pytest.approx(0.08)


class TestMarzy:
    def test_liczona_dla_pelnego_limitu_a_nie_sredniej(self):
        # Klient płacący za 25 000 wiadomości i wysyłający 300 jest zyskowny
        # zawsze. Pytanie brzmi, czy zostaje zyskowny ten, który bierze to,
        # za co zapłacił - stąd liczenie po limicie.
        wynik = marza_planu(PLANS[START], 0.01, CENY)

        assert wynik["koszt_wiadomosci"] == pytest.approx(20.0)
        assert wynik["zostaje"] == pytest.approx(PLANS[START].price_pln - 20.0)

    def test_udzial_kosztu_w_cenie(self):
        wynik = marza_planu(PLANS[START], 0.0149, CENY)

        # 2000 * 0,0149 = 29,8 zł z ceny 149 zł, czyli 20%.
        assert wynik["udzial_kosztu"] == pytest.approx(0.2)


@pytest.mark.django_db
class TestKomendy:
    def test_bez_danych_mowi_wprost_zamiast_pokazywac_zera(self):
        # Zero kosztu i brak danych wyglądają tak samo w tabeli, a znaczą co
        # innego. Tabela z zerami zachęca do wniosku, że usługa nic nie kosztuje.
        strumien = io.StringIO()

        call_command("zmierz_koszt_klienta", stdout=strumien)

        assert "Brak wiadomości z modelu" in strumien.getvalue()

    def test_ujemne_okno_odrzucone(self):
        with pytest.raises(CommandError):
            call_command("zmierz_koszt_klienta", dni=0)
