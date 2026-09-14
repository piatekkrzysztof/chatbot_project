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

Strumień (F16): eksport wysyła plik wiersz po wierszu. Wcześniej `HttpResponse`
zbierał całą historię rozmów firmy w pamięci procesu, zanim wysłał pierwszy
bajt - przy dużej historii to setki megabajtów na jedno żądanie.
"""

import csv

from django.http import StreamingHttpResponse

ZNAKI_FORMUL = ("=", "+", "-", "@", "\t", "\r")
BOM = "﻿"


def bezpieczna_komorka(wartosc):
    """Tekst zaczynający się jak formuła dostaje apostrof; liczby i None bez zmian."""
    if isinstance(wartosc, str) and wartosc.startswith(ZNAKI_FORMUL):
        return "'" + wartosc
    return wartosc


class _Wiersz:
    """Plik, który tylko oddaje zapisany tekst - csv.writer pisze, generator wysyła."""

    def write(self, tekst):
        return tekst


def _linie(naglowek, wiersze):
    pisarz = csv.writer(_Wiersz())
    yield BOM + pisarz.writerow(naglowek)
    for wiersz in wiersze:
        yield pisarz.writerow([bezpieczna_komorka(wartosc) for wartosc in wiersz])


def strumien_csv(nazwa_pliku, naglowek, wiersze):
    """Plik CSV do pobrania, wysyłany w trakcie czytania `wiersze`."""
    odpowiedz = StreamingHttpResponse(_linie(naglowek, wiersze), content_type="text/csv")
    odpowiedz["Content-Disposition"] = f'attachment; filename="{nazwa_pliku}"'
    return odpowiedz
