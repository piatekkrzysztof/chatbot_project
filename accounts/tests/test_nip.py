"""
Suma kontrolna NIP.

Numery użyte w testach to publiczne NIP-y instytucji państwowych albo numery
zbudowane pod algorytm - żaden nie należy do klienta ani do osoby prywatnej.
Sprawdzamy wyłącznie budowę ciągu, nie istnienie firmy.
"""

import pytest

from accounts import nip


class TestPoprawnych:
    def test_numer_policzony_recznie_przechodzi(self):
        """
        5260250274, sprawdzone rachunkiem, nie z pamieci.

          cyfry:  5  2  6  0  2  5  0  2  7  | kontrolna 4
          wagi:   6  5  7  2  3  4  5  6  7
          iloczyny: 30 10 42  0  6 20  0 12 49  ->  suma 169
          169 mod 11 = 4, czyli tyle, ile wynosi ostatnia cyfra

        Pierwsza wersja tego testu wymieniala trzy numery "prawdziwych
        instytucji" wziete z pamieci. Jeden z nich nie mial poprawnej sumy
        kontrolnej i test od razu to pokazal - stad zostaje jeden, za to
        sprawdzony.
        """
        assert nip.poprawny("5260250274")

    @pytest.mark.parametrize(
        "zapis",
        [
            "5260250274",
            "526-025-02-74",
            "526 025 02 74",
            "PL5260250274",
            "  pl526-025-02-74  ",
        ],
    )
    def test_ten_sam_numer_w_roznych_zapisach(self, zapis):
        # Klienci wpisuja NIP na kilka sposobow. Wszystkie znacza to samo,
        # wiec wszystkie musza dac ten sam wynik i te sama postac w bazie.
        assert nip.poprawny(zapis)
        assert nip.znormalizuj(zapis) == "5260250274"


class TestNiepoprawnych:
    def test_przestawione_cyfry_nie_przechodza(self):
        # Najczestsza literowka przy przepisywaniu z dokumentu. Bez sumy
        # kontrolnej taki numer wygladalby na poprawny az do faktury.
        assert nip.poprawny("5260250274")
        assert not nip.poprawny("5260250247")

    @pytest.mark.parametrize(
        "numer",
        ["", "123", "12345678901", "abcdefghij", None],
    )
    def test_smieci_nie_przechodza(self, numer):
        assert not nip.poprawny(numer)

    def test_same_zera_nie_przechodza_mimo_poprawnej_sumy(self):
        """
        Znalezione przez ten test, nie zalozone z gory.

        Same zera SPELNIAJA sume kontrolna: 0 mod 11 = 0, czyli tyle, ile
        wynosi ostatnia cyfra. Zaden numer nigdy nie zostal tak nadany, a
        wypelnienie pola zerami to odruch kogos, kto chce ominac wymagany
        formularz - wiec bez osobnej reguly taki wpis wygladalby na poprawny
        az do faktury.
        """
        assert not nip.poprawny("0000000000")

    def test_zla_cyfra_kontrolna_nie_przechodzi(self):
        # Ten sam numer z podmieniona ostatnia cyfra.
        assert not nip.poprawny("5260250275")


class TestFormatowania:
    def test_zapis_z_myslnikami(self):
        assert nip.sformatuj("5260250274") == "526-025-02-74"

    def test_niepoprawny_numer_zostaje_bez_zmian(self):
        # Formatowanie nie jest miejscem na ukrywanie bledu - jesli numer nie
        # ma dziesieciu cyfr, pokazujemy go tak, jak zostal wpisany.
        assert nip.sformatuj("123") == "123"
