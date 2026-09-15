"""
Zgodność dokumentacji (F24): odnośniki między dokumentami prowadzą do plików, które istnieją.

Roadmapa, opisy zmian i README odsyłają do siebie nawzajem i do instrukcji
odbioru. Przeniesienie albo zmiana nazwy pliku zostawiała martwy odnośnik,
który wychodził na jaw dopiero przy odbiorze - wtedy, gdy instrukcja jest
potrzebna.
"""

import re
from pathlib import Path

KATALOG = Path(__file__).resolve().parents[2]
ODNOSNIK = re.compile(r"\]\(([^)\s]+)\)")


def dokumenty():
    pliki = sorted((KATALOG / "docs").glob("*.md"))
    return pliki + [p for p in (KATALOG / "README.md", KATALOG / "CHANGELOG.md") if p.exists()]


def test_odnosniki_w_dokumentacji_prowadza_do_istniejacych_plikow():
    martwe = []
    for plik in dokumenty():
        for cel in ODNOSNIK.findall(plik.read_text(encoding="utf-8")):
            if cel.startswith(("http://", "https://", "mailto:", "#")):
                continue
            sciezka = cel.split("#", 1)[0]
            if sciezka and not (plik.parent / sciezka).exists():
                martwe.append(f"{plik.relative_to(KATALOG)} -> {cel}")

    assert len(dokumenty()) > 10
    assert martwe == []
