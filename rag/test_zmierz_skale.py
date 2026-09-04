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
