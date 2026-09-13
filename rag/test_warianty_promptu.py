"""
Testy wariantów promptu do pomiaru - czy wariant zmienia dokładnie to, co mówi
jego nazwa, i czy podmiana nie wycieka poza pomiar.

Wariant, który po cichu nic nie zmienia, dałby dwa identyczne pomiary pod
dwiema nazwami - i decyzję o poprawce promptu podjętą na szumie.
"""

from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.management import call_command

from accounts.models import Tenant
from api.utils import chat_engine
from api.utils.pokrycie import ZNACZNIK_BRAKU
from api.utils.prompt_systemowy import OGRANICZNIK, PRZYPOMNIENIE_O_ZNACZNIKU, build_system_prompt
from rag.ocena.generowanie import ocen_generowanie
from rag.ocena.korpus import DO_WEKTOROW
from rag.ocena.warianty_promptu import WARIANTY, WariantNieaktualny, wariant_promptu

pytestmark = pytest.mark.django_db


@pytest.fixture
def prompt():
    firma = Tenant.objects.create(
        name="Rowerownia", gpt_prompt="Sklep rowerowy w Krakowie.", regulamin="Zwroty do 14 dni."
    )
    fragment = SimpleNamespace(content="Przeglad 120 zl.", document=SimpleNamespace(name="Cennik"))
    faq = SimpleNamespace(question="Czy macie parking?", answer="Tak, przed sklepem.")
    return build_system_prompt(firma, [fragment], [faq], message="Ile kosztuje przeglad?")


class TestPrzeksztalcen:
    def test_obecny_to_prompt_produkcyjny(self, prompt):
        assert WARIANTY["obecny"](prompt) == prompt
        assert prompt.endswith(PRZYPOMNIENIE_O_ZNACZNIKU)

    def test_bez_przypomnienia_to_prompt_sprzed_poprawki(self, prompt):
        wynik = WARIANTY["bez-przypomnienia"](prompt)
        assert wynik + PRZYPOMNIENIE_O_ZNACZNIKU == prompt
        assert "Pamiętaj:" not in wynik

    def test_bez_zdania_o_danych_usuwa_tylko_to_zdanie(self, prompt):
        wynik = WARIANTY["bez-zdania-o-danych"](prompt)
        assert "DANE firmy" not in wynik
        # Zdanie wymienia ogranicznik raz; bloki wiedzy i przypomnienie zostają.
        assert wynik.count(OGRANICZNIK) == prompt.count(OGRANICZNIK) - 1
        assert f"{OGRANICZNIK} Regulamin" in wynik
        assert wynik.endswith(PRZYPOMNIENIE_O_ZNACZNIKU)
        assert len(prompt) - len(wynik) < 500

    def test_sprzed_f25_ma_bloki_w_starym_formacie(self, prompt):
        wynik = WARIANTY["sprzed-f25"](prompt)
        assert OGRANICZNIK not in wynik
        assert "Pamiętaj:" not in wynik
        assert "\nO firmie:\nSklep rowerowy w Krakowie." in wynik
        assert "\nNajczęstsze pytania i odpowiedzi:\nP: Czy macie parking?" in wynik
        assert "\nFragmenty dokumentów firmy:\n[Źródło: Cennik]\nPrzeglad 120 zl." in wynik
        assert "\nRegulamin:\nZwroty do 14 dni." in wynik
        # Reguła znacznika zostaje - wariant zmienia tylko to, co wniosło F25 i poprawka.
        assert f"ZACZNIJ odpowiedź dokładnie od {ZNACZNIK_BRAKU}" in wynik

    @pytest.mark.parametrize(
        "nazwa,tekst",
        [
            ("bez-zdania-o-danych", "Prompt, w którym tego zdania już nie ma."),
            ("bez-przypomnienia", "Prompt bez przypomnienia na końcu."),
        ],
    )
    def test_wariant_bez_czego_zmieniac_rzuca_bledem(self, nazwa, tekst):
        """Inaczej zmierzyłby po cichu obecny prompt pod inną nazwą."""
        with pytest.raises(WariantNieaktualny):
            WARIANTY[nazwa](tekst)

    def test_nieznany_wariant(self):
        with pytest.raises(ValueError, match="Nieznany wariant"):
            with wariant_promptu("najlepszy"):
                pass


def systemowe(wolanie):
    return [zapis.args[0][0]["content"] for zapis in wolanie.call_args_list]


def zmierz(wariant):
    with patch(
        "rag.ocena.generowanie.get_openai_response",
        side_effect=lambda *a, **k: {"content": "Odpowiedz.", "tokens": 1},
    ) as wolanie:
        ocen_generowanie(model="model-testowy", powtorzen=1, wariant=wariant)
    return wolanie


class TestPodmianyWPomiarze:
    def test_wariant_trafia_do_modelu(self):
        wiadomosci = systemowe(zmierz("bez-przypomnienia"))
        assert len(wiadomosci) == len(DO_WEKTOROW)
        assert not any(tresc.endswith(PRZYPOMNIENIE_O_ZNACZNIKU) for tresc in wiadomosci)

    def test_bez_wariantu_prompt_produkcyjny(self):
        wiadomosci = systemowe(zmierz(None))
        assert all(tresc.endswith(PRZYPOMNIENIE_O_ZNACZNIKU) for tresc in wiadomosci)

    def test_podmiana_nie_zostaje_po_pomiarze(self):
        """Produkcja w tym samym procesie musi dostać swój prompt."""
        zmierz("sprzed-f25")
        assert chat_engine.build_system_prompt is build_system_prompt


def test_komenda_porownuje_wszystkie_warianty_na_calym_korpusie(settings):
    """
    Wszystkie warianty przez prawdziwą komendę i cały korpus - także pytania bez
    fragmentów, gdzie prompt ma inny kształt. Wariant, który nie pasuje do
    któregoś promptu, kończy się w komendzie błędem i pomija swoje wywołania,
    więc pełna liczba wywołań dowodzi, że każdy przeszedł.
    """
    settings.OPENAI_API_KEY = "klucz-testowy"
    wyjscie = StringIO()
    argumenty = ["ocen_generowanie", "--powtorzen", "1"]
    for nazwa in WARIANTY:
        argumenty += ["--wariant", nazwa]
    with patch(
        "rag.ocena.generowanie.get_openai_response",
        side_effect=lambda *a, **k: {"content": "Odpowiedz.", "tokens": 1},
    ) as wolanie:
        call_command(*argumenty, stdout=wyjscie)

    tekst = wyjscie.getvalue()
    assert wolanie.call_count == len(WARIANTY) * len(DO_WEKTOROW), tekst[-2000:]
    assert all(f"[{nazwa}]" in tekst for nazwa in WARIANTY)
    assert "POROWNANIE" in tekst
    assert "produkcja bez zmian" in tekst

    # Liczba wywołań i etykiety nie wystarczą: komenda, która nie przekazuje
    # wariantu dalej, mierzy cztery razy prompt produkcyjny pod czterema
    # nazwami. Wyszło przy weryfikacji mutacyjnej. Sprawdzamy więc to, co
    # model naprawdę dostał.
    prompty = systemowe(wolanie)
    n = len(DO_WEKTOROW)
    assert (
        sum(p.endswith(PRZYPOMNIENIE_O_ZNACZNIKU) for p in prompty) == 2 * n
    )  # obecny, bez-zdania
    assert sum("DANE firmy" not in p for p in prompty) == 2 * n  # bez-zdania, sprzed-f25
