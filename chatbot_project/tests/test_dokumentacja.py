"""
Zgodność dokumentacji (F24): odnośniki między dokumentami prowadzą do plików, które istnieją.

Roadmapa, opisy zmian i README odsyłają do siebie nawzajem i do instrukcji
odbioru. Przeniesienie albo zmiana nazwy pliku zostawiała martwy odnośnik,
który wychodził na jaw dopiero przy odbiorze - wtedy, gdy instrukcja jest
potrzebna.

Od 29.09.2026 sprawdzamy też część po `#`. Poprzednia wersja obcinała ją
i patrzyła wyłącznie na nazwę pliku, więc odnośnik do sekcji, której już nie
ma, przechodził. Tak właśnie przeżył odnośnik do „Dlaczego bez nowego
usuwania": nagłówek zniknął przy okazji raportu retencji, plik został, test
milczał. Odnośnik do sekcji jest w dokumentacji odbioru najczęstszy -
„instrukcja jest tutaj" znaczy konkretny akapit, nie plik na czterysta wierszy.
"""

import re
from pathlib import Path

KATALOG = Path(__file__).resolve().parents[2]
ODNOSNIK = re.compile(r"\]\(([^)\s]+)\)")
NAGLOWEK = re.compile(r"^#{1,6}\s+(.*?)\s*$", re.MULTILINE)
ODNOSNIK_W_NAGLOWKU = re.compile(r"\[([^\]]*)\]\([^)]*\)")
ZNACZNIKI = re.compile(r"[`*_~]")
NIE_DO_SLUGA = re.compile(r"[^\w\- ]", re.UNICODE)


def dokumenty():
    pliki = sorted((KATALOG / "docs").glob("*.md"))
    return pliki + [p for p in (KATALOG / "README.md", KATALOG / "CHANGELOG.md") if p.exists()]


def kotwice(tekst):
    """
    Kotwice nagłówków tak, jak liczy je GitHub.

    Z nagłówka znika formatowanie i interpunkcja, spacje zamieniają się
    w myślniki, reszta idzie małymi literami. Powtórzony nagłówek dostaje
    kolejny numer - stąd licznik.
    """
    wynik = set()
    uzyte = {}
    for naglowek in NAGLOWEK.findall(tekst):
        czysty = ODNOSNIK_W_NAGLOWKU.sub(r"\1", naglowek)
        czysty = ZNACZNIKI.sub("", czysty)
        slug = NIE_DO_SLUGA.sub("", czysty).strip().lower().replace(" ", "-")
        if slug in uzyte:
            uzyte[slug] += 1
            slug = f"{slug}-{uzyte[slug]}"
        else:
            uzyte[slug] = 0
        wynik.add(slug)
    return wynik


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


def test_odnosniki_do_sekcji_prowadza_do_istniejacych_naglowkow():
    """
    Część po `#` też musi coś znaczyć.

    Odnośnik do sekcji, która zniknęła, jest gorszy od odnośnika do pliku,
    którego nie ma: przeglądarka otwiera dokument i zostawia czytelnika na
    górze, bez żadnego znaku, że szukanej sekcji nie ma. Wygląda jak działający
    odnośnik, tylko prowadzi w złe miejsce.
    """
    martwe = []
    sprawdzone = 0
    for plik in dokumenty():
        for cel in ODNOSNIK.findall(plik.read_text(encoding="utf-8")):
            if cel.startswith(("http://", "https://", "mailto:")):
                continue
            if "#" not in cel:
                continue
            sciezka, _, kotwica = cel.partition("#")
            docelowy = (plik.parent / sciezka) if sciezka else plik
            if not docelowy.exists():
                # Brakujący plik zgłasza już test wyżej; tu nie dublujemy.
                continue
            sprawdzone += 1
            if not kotwica or kotwica not in kotwice(docelowy.read_text(encoding="utf-8")):
                martwe.append(f"{plik.relative_to(KATALOG)} -> {cel}")

    # Bez tego test przechodziłby również wtedy, gdyby wyrażenie przestało
    # cokolwiek znajdować - a zero sprawdzonych odnośników wygląda dokładnie
    # tak samo jak zero martwych.
    assert sprawdzone > 10
    assert martwe == []


def test_kotwice_liczone_tak_jak_na_githubie():
    """
    Reguły slugów są drobne i łatwo je zgubić przy refaktorze.

    Bez tego testu całe sprawdzanie sekcji mogłoby po cichu przestać cokolwiek
    znajdować: kotwica wyliczona inaczej niż przez GitHuba nie pasuje do
    niczego, więc albo zgłasza jako martwe wszystko, albo - po dodaniu wyjątku
    na to - nie zgłasza nic.
    """
    tekst = "\n".join(
        [
            "## Dane osobowe i czas przechowywania",
            "## Wynik odbioru - 17.09.2026",
            "## Jak to działa: `accounts/retencja.py`",
            "## Powtórka",
            "## Powtórka",
        ]
    )

    assert kotwice(tekst) == {
        "dane-osobowe-i-czas-przechowywania",
        # Kropki znikają, myślnik zostaje, spacje wokół niego też - stąd trzy
        # myślniki z rzędu.
        "wynik-odbioru---17092026",
        # Dwukropek i ukośnik odpadają, polskie znaki i treść backticków nie.
        "jak-to-działa-accountsretencjapy",
        "powtórka",
        "powtórka-1",
    }
