"""
Pliki przepływów GitHub Actions muszą dać się wczytać.

14.11.2026 w komentarzu skryptu w `kontrola-kopii.yml` znalazł się zapis pustego
wyrażenia. GitHub rozwija wyrażenia w całej treści kroku, także w komentarzach,
a puste jest błędem składni - więc unieważnił cały plik. Przepływ działa tylko
z harmonogramu, dlatego nie pokazał tego żaden przebieg na PR: poniedziałkowa
kontrola kopii po prostu się nie odbyła, bez żadnego alarmu.

Lokalny parser YAML niczego tu nie widzi (dla niego to zwykły tekst), stąd
osobne sprawdzenie samych wyrażeń.
"""

import re
from pathlib import Path

import pytest
import yaml

KATALOG = Path(__file__).resolve().parents[2] / ".github" / "workflows"
PRZEPLYWY = sorted(KATALOG.glob("*.yml"))
WYRAZENIE = re.compile(r"\$\{\{(.*?)\}\}", re.S)


def test_sa_jakies_przeplywy():
    assert PRZEPLYWY, f"Brak plików w {KATALOG}"


@pytest.mark.parametrize("plik", PRZEPLYWY, ids=lambda p: p.name)
def test_zadne_wyrazenie_nie_jest_puste(plik):
    tresc = plik.read_text(encoding="utf-8")
    puste = [
        tresc.count("\n", 0, trafienie.start()) + 1
        for trafienie in WYRAZENIE.finditer(tresc)
        if not trafienie.group(1).strip()
    ]
    assert not puste, f"{plik.name}: puste wyrażenie w wierszach {puste} unieważnia cały plik"


@pytest.mark.parametrize("plik", PRZEPLYWY, ids=lambda p: p.name)
def test_kazde_otwarte_wyrazenie_jest_zamkniete(plik):
    tresc = plik.read_text(encoding="utf-8")
    assert tresc.count("${{") == len(WYRAZENIE.findall(tresc)), (
        f"{plik.name}: niezamknięte wyrażenie"
    )


@pytest.mark.parametrize("plik", PRZEPLYWY, ids=lambda p: p.name)
def test_plik_jest_poprawnym_yaml_z_zadaniami(plik):
    dane = yaml.safe_load(plik.read_text(encoding="utf-8"))
    assert dane.get("jobs"), f"{plik.name}: brak zadań"
    # Klucz `on` parser YAML czyta jako wartość logiczną True.
    assert dane.get("on") or dane.get(True), f"{plik.name}: brak wyzwalaczy"
