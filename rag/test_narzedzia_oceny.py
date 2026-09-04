"""
Narzędzia wokół oceny: komendy i zabezpieczenia miar.

Kategoria ryzyka: PRZYRZĄD POMIAROWY. Ocena wyszukiwania jest po to, żeby
wykryć pogorszenie. Jeśli sam przyrząd da się bezwiednie przestawić - nadpisać
wzorzec, policzyć średnią z jednej grupy pytań - to zamiast miary mamy lustro,
które pokazuje to, co chcemy zobaczyć.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import CommandError, call_command
from django.core.management.base import OutputWrapper

from rag.ocena.korpus import Pytanie
from rag.ocena.miary import WynikPytania, opisz_bledy, policz


class TestZabezpieczenMiar:
    """Miary muszą odmówić policzenia czegoś, co nie ma sensu."""

    def test_sam_zestaw_z_odpowiedziami_jest_odrzucany(self):
        """
        Zestaw bez pytan spoza bazy wiedzy mierzylby wylacznie trafnosc -
        czyli nagradzal wyszukiwarke, ktora na kazde pytanie cos zwraca.
        To jest dokladnie ta wada, przed ktora cala ta ocena ma chronic,
        wiec nie wolno jej wpuscic tylnymi drzwiami przez okrojony zestaw.
        """
        wyniki = [
            WynikPytania(
                pytanie=Pytanie("Ile kosztuje przeglad?", frozenset({"cennik"})),
                znalezione=("cennik",),
            )
        ]

        with pytest.raises(ValueError, match="bez odpowiedzi"):
            policz(wyniki)

    def test_sam_zestaw_bez_odpowiedzi_tez_jest_odrzucany(self):
        # Odwrotna skrajnosc: mierzylibysmy wylacznie cisze, czyli nagradzali
        # wyszukiwarke, ktora nie zwraca nigdy niczego.
        wyniki = [WynikPytania(pytanie=Pytanie("Jaka jest stolica Australii?"), znalezione=())]

        with pytest.raises(ValueError, match="nie ma czego mierzyc"):
            policz(wyniki)

    def test_pozycja_liczy_sie_od_jedynki(self):
        # Liczona od zera dalaby dzielenie przez zero w sredniej odwrotnej
        # pozycji przy trafieniu na pierwszym miejscu.
        wynik = WynikPytania(
            pytanie=Pytanie("pytanie", frozenset({"b"})),
            znalezione=("a", "b", "c"),
        )

        assert wynik.pozycja == 2

    def test_opis_bledow_rozroznia_dwa_rodzaje_pomylki(self):
        wyniki = [
            WynikPytania(Pytanie("pytanie z odpowiedzia", frozenset({"x"})), znalezione=("y",)),
            WynikPytania(Pytanie("pytanie spoza bazy"), znalezione=("z",)),
        ]

        opis = "\n".join(opisz_bledy(wyniki))

        # Nieznalezienie i nieprzemilczenie to dwie rozne usterki i wymagaja
        # dwoch roznych reakcji - opis musi je rozdzielac.
        assert "NIE ZNALAZL" in opis
        assert "NIE ZAMILKL" in opis


@pytest.mark.django_db
class TestKomendyOcen:
    def test_komenda_wypisuje_obie_miary(self):
        wyjscie = OutputWrapper(MagicMock())
        with patch.object(OutputWrapper, "write") as pisz:
            call_command("ocen_rag", stdout=wyjscie)

        tekst = " ".join(str(wywolanie.args[0]) for wywolanie in pisz.call_args_list)
        assert "trafnosc" in tekst
        assert "cisza" in tekst

    def test_przemiatanie_pokazuje_wymiane(self):
        wyjscie = OutputWrapper(MagicMock())
        with patch.object(OutputWrapper, "write") as pisz:
            call_command("ocen_rag", przemiataj=True, stdout=wyjscie)

        tekst = " ".join(str(wywolanie.args[0]) for wywolanie in pisz.call_args_list)
        assert "1.15" in tekst
        assert "obecny" in tekst

    def test_komenda_nie_zostawia_smieci_w_bazie(self):
        """
        Korpus wjezdza do bazy jako prawdziwe dokumenty. Bez wycofania
        transakcji komenda diagnostyczna zostawialaby w bazie klienta
        wymyslona firme z cennikiem rowerow - i to przy kazdym uruchomieniu.
        """
        from accounts.models import Tenant

        przed = Tenant.objects.count()
        call_command("ocen_rag", stdout=OutputWrapper(MagicMock()))

        assert Tenant.objects.count() == przed


class TestOchronyWzorca:
    def test_wzorzec_nie_nadpisuje_sie_bez_wyraznej_zgody(self):
        """
        Najważniejszy test w tym pliku.

        Wzorzec jest punktem odniesienia. Gdyby przeliczal sie przy kazdym
        uruchomieniu, kazde pogorszenie jakosci zostaloby natychmiast uznane
        za nowa norme - a test regresji przestalby cokolwiek wykrywac,
        pokazujac przy tym zielone swiatlo.
        """
        with pytest.raises(CommandError, match="--wymus"):
            call_command("zbuduj_wzorzec_rag")

    def test_wzorzec_ma_ksztalt_ktorego_oczekuje_ocena(self):
        from rag.ocena.korpus import FRAGMENTY, PYTANIA
        from rag.ocena.przebieg import SCIEZKA_WZORCA

        wzorzec = json.loads(SCIEZKA_WZORCA.read_text(encoding="utf-8"))

        # Wzorzec i korpus musza sie zgadzac co do joty. Dopisane pytanie bez
        # przeliczenia wektorow wywalilo by ocene dopiero w trakcie przebiegu,
        # z bledem o brakujacym kluczu zamiast o nieaktualnym wzorcu.
        assert set(wzorzec["fragmenty"]) == set(FRAGMENTY)
        assert set(wzorzec["pytania"]) == {pytanie.tresc for pytanie in PYTANIA}
        assert wzorzec["wymiarow"] == 1536
