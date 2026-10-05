"""
Budżet pamięci parsera plików na małej instancji.

Kategoria ryzyka: FUNKCJA, KTÓRA NA PRODUKCJI NIE DZIAŁA WCALE. Odbiór 5.10.2026
na Render Starter (512 MiB): każde wgranie dokumentu kończyło się odmową
„Serwer nie ma teraz zasobów", także dla kilkubajtowego pliku tekstowego.
Odczyt cgroup: 312 MiB zajęte, budżet 99,8 MiB przy progu 96 MiB - samo
żądanie z plikiem przechylało go pod próg.

Parser dostaje budżet jako twardy limit przestrzeni adresowej, więc nie zajmie
więcej. Reguła „połowa wolnej pamięci" pilnowała więc procesu web podwójnie.
Te testy sprawdzają obie strony: upload ma się mieścić na 512 MiB, a kontener
nie może nigdy przekroczyć limitu.
"""

from pathlib import Path

import pytest

from documents import isolated_parser as parser

MIB = 1024 * 1024
LIMIT = 512 * MIB


def cgroup(monkeypatch, zajete):
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self: str(LIMIT if self.name == "memory.max" else zajete),
    )


def test_upload_miesci_sie_na_512_mib_w_trakcie_zadania(monkeypatch):
    """
    Ten test padał na kodzie sprzed 2.22.0.

    312 MiB to odczyt z produkcji w spoczynku; samo żądanie z plikiem dokłada
    swoje - tu 18 MiB. Połowa z pozostałych 182 MiB to 91 MiB, pod progiem 96.
    """
    cgroup(monkeypatch, 330 * MIB)

    assert parser.memory_budget() >= parser.PARSER_MINIMUM_BYTES


@pytest.mark.parametrize("zajete_mib", [200, 280, 312, 330, 350])
def test_kontener_nigdy_nie_przekracza_limitu(monkeypatch, zajete_mib):
    """
    Obietnica, na której stoi cała reguła.

    Parser nie zajmie więcej niż budżet (RLIMIT_AS), a proces web urośnie
    w trakcie żądania najwyżej o rezerwę. Suma musi zmieścić się w limicie.
    """
    cgroup(monkeypatch, zajete_mib * MIB)

    budzet = parser.memory_budget()

    assert zajete_mib * MIB + budzet + parser.REZERWA_USLUGI <= LIMIT


def test_gorny_limit_parsera_zostaje(monkeypatch):
    """Dużo wolnej pamięci nie daje parserowi więcej niż 192 MiB."""
    cgroup(monkeypatch, 50 * MIB)

    assert parser.memory_budget() == parser.PARSER_MEMORY_BYTES


def test_za_malo_pamieci_nadal_odmawia(monkeypatch):
    """Rezerwa nie może zamienić się w zgodę na wszystko."""
    cgroup(monkeypatch, 360 * MIB)

    with pytest.raises(parser.ParserUnavailable, match="zasobów"):
        parser.memory_budget()


def test_rezerwa_i_minimum_sa_przypiete():
    """Zmiana tych liczb zmienia ryzyko wywrócenia usługi - to decyzja, nie porządki."""
    assert parser.REZERWA_USLUGI == 64 * MIB
    assert parser.PARSER_MINIMUM_BYTES == 96 * MIB
    assert parser.PARSER_MEMORY_BYTES == 192 * MIB
