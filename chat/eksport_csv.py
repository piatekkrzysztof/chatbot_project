"""
Eksport CSV, który da się bezpiecznie otworzyć w arkuszu.

Treść rozmów pisze odwiedzający strony klienta, więc jest niezaufana. Komórka
zaczynająca się od "=", "+", "-", "@", tabulatora albo powrotu karetki jest
w Excelu, LibreOffice i Arkuszach Google traktowana jak formuła. Wystarczyło
wpisać w widgecie `=HYPERLINK("http://...";"Kliknij")`, a właściciel po
otwarciu eksportu dostawał w arkuszu aktywny link albo formułę wykonującą
polecenie (DDE). Wcześniej tekst szedł do pliku bez zmian.

Neutralizacja według OWASP (CSV Injection): taka komórka dostaje z przodu
apostrof. Arkusz pokazuje ją jako tekst, a treść zostaje czytelna.

BOM na początku pliku: Excel na polskim Windowsie otwiera CSV bez BOM jako
Windows-1250 i zamienia polskie litery w krzaczki.
"""

import csv

from django.http import HttpResponse

ZNAKI_FORMUL = ("=", "+", "-", "@", "\t", "\r")
BOM = "﻿"


def bezpieczna_komorka(wartosc):
    """Tekst zaczynający się jak formuła dostaje apostrof; liczby i None bez zmian."""
    if isinstance(wartosc, str) and wartosc.startswith(ZNAKI_FORMUL):
        return "'" + wartosc
    return wartosc


def odpowiedz_csv(nazwa_pliku):
    """Odpowiedź do pobrania z BOM już na początku treści."""
    odpowiedz = HttpResponse(content_type="text/csv")
    odpowiedz["Content-Disposition"] = f'attachment; filename="{nazwa_pliku}"'
    odpowiedz.write(BOM)
    return odpowiedz


class BezpiecznyWriter:
    """csv.writer, który neutralizuje każdą komórkę przed zapisem."""

    def __init__(self, plik):
        self._writer = csv.writer(plik)

    def writerow(self, wiersz):
        self._writer.writerow([bezpieczna_komorka(wartosc) for wartosc in wiersz])
