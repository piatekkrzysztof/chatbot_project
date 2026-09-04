"""
Komenda mierząca skalę wyszukiwania.

Kategoria ryzyka: NARZĘDZIE POMIAROWE. Ta komenda zakłada w bazie firmę
z dziesiątkami tysięcy wierszy. Jeśli ich po sobie nie posprząta - zwłaszcza
gdy pomiar przerwie błąd - zostawi w bazie klienta atrapę większą niż jego
własne dane, a nikt tego nie zauważy, dopóki nie zajrzy.

Drugie ryzyko: wektory mają być losowe. Gdyby komenda liczyła prawdziwe,
pomiar skali planu Pro kosztowałby sto tysięcy wywołań płatnego API.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import OutputWrapper

from accounts.models import Tenant
from documents.models import DocumentChunk

pytestmark = pytest.mark.django_db


def uruchom(**opcje):
    call_command("zmierz_skale", stdout=OutputWrapper(MagicMock()), **opcje)


class TestSprzatania:
    def test_nie_zostawia_danych_po_udanym_pomiarze(self):
        przed_firm = Tenant.objects.count()

        uruchom(do=1000)

        assert Tenant.objects.count() == przed_firm
        assert DocumentChunk.objects.count() == 0

    def test_nie_zostawia_danych_po_bledzie(self):
        """
        Najważniejszy test w tym pliku.

        Pomiar przerwany w polowie - Ctrl+C, brak miejsca, cokolwiek - zostawia
        w bazie tyle wierszy, ile zdazyl utworzyc. Bez sprzatania w `finally`
        byloby to dziesiatki tysiecy fragmentow wymyslonej firmy.
        """
        przed_firm = Tenant.objects.count()

        with patch(
            "rag.management.commands.zmierz_skale.Command._czas",
            side_effect=RuntimeError("pomiar przerwany"),
        ):
            with pytest.raises(RuntimeError):
                uruchom(do=1000)

        assert Tenant.objects.count() == przed_firm
        assert DocumentChunk.objects.count() == 0


class TestKosztu:
    def test_nie_wola_zadnego_api(self):
        """
        Wektory sa losowe swiadomie: koszt liczenia odleglosci nie zalezy od
        ich wartosci, a policzenie stu tysiecy prawdziwych kosztowaloby realne
        pieniadze i nic by nie wnioslo.
        """
        with patch("openai.OpenAI") as klient:
            uruchom(do=1000)

        assert klient.call_count == 0

    def test_nie_zleca_generowania_wektorow(self):
        # Dokument z processed=True i bez fragmentow odpala sygnal post_save.
        # Ta sama pulapka, ktora wczesniej zdublowala fragmenty w demo.
        with patch("documents.signals.enqueue") as zlecenie:
            uruchom(do=1000)

        assert zlecenie.call_count == 0


class TestWyniku:
    def test_wypisuje_cennik_i_pomiar(self):
        with patch.object(OutputWrapper, "write") as pisz:
            uruchom(do=1000)

        tekst = " ".join(str(w.args[0]) for w in pisz.call_args_list if w.args)

        # Bez zestawienia z cennikiem liczby nie mowia, ktory plan sprzedaje
        # wiecej, niz obsluzymy szybko - a to jest cale pytanie.
        assert "plan" in tekst
        assert "fragmentow" in tekst
        assert "mediana" in tekst
        assert "1,000" in tekst


class TestZabezpieczeniaPrzedZapisemDoProdukcji:
    """
    Komenda pisze do bazy, z którą jest połączona.

    Uruchomiona w powłoce hostingu pisze do bazy PRODUKCYJNEJ, a pełny przebieg
    to ponad 680 MB - rozmiar zdolny zapełnić dysk małej instancji. Pierwsza
    wersja miała 85 000 jako wartość domyślną i nie mówiła o tym ani słowa.
    """

    def test_duzy_pomiar_wymaga_swiadomej_zgody(self):
        from django.core.management.base import CommandError

        with pytest.raises(CommandError, match="wiem-ze-pisze-do-tej-bazy"):
            uruchom(do=85_000)

    def test_z_potwierdzeniem_przechodzi(self):
        # Sam prog, nie caly pomiar - 85 000 fragmentow zajeloby minuty.
        uruchom(do=1000, wiem_ze_pisze_do_tej_bazy=True)

        assert DocumentChunk.objects.count() == 0

    def test_odmowa_podaje_rozmiar_i_nazwe_bazy(self):
        """
        Komunikat bez liczby i bez nazwy bazy kaze zgadywac, czego dotyczy -
        a to jest dokladnie ta chwila, w ktorej nie wolno zgadywac.
        """
        from django.conf import settings
        from django.core.management.base import CommandError

        with pytest.raises(CommandError) as blad:
            uruchom(do=85_000)

        tresc = str(blad.value)
        assert "MB" in tresc
        assert str(settings.DATABASES["default"]["NAME"]) in tresc

    def test_domyslny_rozmiar_nie_wymaga_zgody(self):
        from rag.management.commands.zmierz_skale import (
            DOMYSLNY_ROZMIAR,
            PROG_POTWIERDZENIA,
        )

        # Gdyby domyslna wartosc przekroczyla prog, kazde uruchomienie
        # zaczynaloby sie od bledu - a zabezpieczenie, ktore blokuje normalne
        # uzycie, zostaje wylaczone przy pierwszej okazji.
        assert DOMYSLNY_ROZMIAR <= PROG_POTWIERDZENIA
