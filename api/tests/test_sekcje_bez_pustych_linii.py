"""
Sekcje w tekście bez pustych linii (PDF, DOCX) - 2.26.0.

Kategoria ryzyka: WIEDZA, KTÓRA JEST, A BOT JEJ NIE ZNAJDUJE. Tekst z PDF-a
i DOCX-a nie ma pustych linii między akapitami, a podział szukał granic sekcji
właśnie po nich. Trzystronicowa oferta z PDF-a dawała trzy fragmenty - po
jednym na stronę - i pytanie o anulowanie trafiało we fragment „anulowanie +
płatność + kontakt" za progiem. Pomiar 8.10.2026 na pięciu dokumentach:
17 z 22 pytań przed zmianą, 22 z 22 po, cisza bez zmian.
"""

import time

from documents.utils.fragmenty import podziel_na_fragmenty
from rag.engine import slowa_kluczowe

# Tak wygląda oferta po ekstrakcji z PDF-a: akapity i nagłówki w kolejnych
# liniach, wypunktowanie odczytane jako \x7f, tabela komórka pod komórką.
OFERTA_Z_PDF = """Smaki Doliny - oferta cateringu
Przygotowujemy jedzenie na chrzciny, komunie i spotkania firmowe w Wałbrzychu.
Pakiety i ceny
Pakiet
Cena za osobę
Bufet Klasyczny
89 zł
2 dania ciepłe, 3 sałatki, przekąski
Bufet Premium
139 zł
3 dania ciepłe, deska serów, deser
Dowóz i obsługa
\x7f Dowóz do 15 km gratis, dalej 3 zł za kilometr w jedną stronę.
\x7f Kelner kosztuje 45 zł za godzinę, minimum 4 godziny.
Zmiany i anulowanie
Anulowanie do 14 dni przed przyjęciem - zwracamy całą zaliczkę. Od 13 do 5 dni -
zwracamy połowę. Później zaliczka przepada.
Kontakt
Biuro odpowiada od poniedziałku do piątku w godzinach 8-16, w soboty 9-13."""


def fragment_z(fragmenty, szukane):
    return next(f for f in fragmenty if szukane in f)


def test_kazda_sekcja_z_pdf_ma_wlasny_fragment():
    """Ten test padał przed 2.26.0: anulowanie dzieliło fragment z kontaktem."""
    fragmenty = podziel_na_fragmenty(OFERTA_Z_PDF)

    anulowanie = fragment_z(fragmenty, "Zmiany i anulowanie")
    assert "połowę" in anulowanie
    assert "Biuro odpowiada" not in anulowanie
    assert "Kelner" not in anulowanie
    assert fragment_z(fragmenty, "Kontakt\nBiuro").startswith("Kontakt")


def test_komorki_tabeli_z_pdf_nie_sa_naglowkami():
    """„Bufet Premium" stoi po „przekąski" bez kropki - to komórka, nie sekcja."""
    fragmenty = podziel_na_fragmenty(OFERTA_Z_PDF)

    tabela = fragment_z(fragmenty, "Pakiety i ceny")
    assert "Bufet Klasyczny" in tabela and "Bufet Premium\n139 zł" in tabela
    assert not any(f.startswith(("Bufet Premium", "139 zł", "Pakiet\n")) for f in fragmenty)


def test_linia_lamana_w_polowie_zdania_nie_jest_naglowkiem():
    tekst = (
        "Regulamin obowiązuje wszystkich klientów, którzy składają zamówienia przez\n"
        "Stronę internetową, telefonicznie albo osobiście w pracowni\n"
        "Od pierwszego dnia miesiąca, bez wyjątków i bez dodatkowych dopłat dla nikogo."
    )
    # Druga linia wygląda jak nagłówek: krótka, wielka litera, bez kropki,
    # a po niej idzie długa treść. Zdradza ją dopiero poprzednia linia, która
    # nie kończy zdania - to łamanie wiersza, nie nowa sekcja.
    assert len(podziel_na_fragmenty(tekst)) == 1


def test_komorka_tabeli_z_dlugim_opisem_nie_jest_naglowkiem():
    """Po „Bufet Premium" idzie ponad 60 znaków - zatrzymuje ją poprzednia komórka."""
    tekst = (
        "Pakiety i ceny\n"
        "Bufet Klasyczny\n89 zł\n2 dania ciepłe, 3 sałatki, przekąski\n"
        "Bufet Premium\n139 zł\n"
        "3 dania ciepłe, deska serów, deser, napoje bez limitu i obsługa przez cały wieczór"
    )
    assert len(podziel_na_fragmenty(tekst)) == 1


def test_naglowek_tabeli_zostaje_w_swojej_sekcji():
    tekst = (
        "Cennik dekoracji\n"
        "Ceny brutto obowiązują od października i dotyczą zamówień z tortem.\n"
        "Usługa | Cena | Uwagi\n"
        "Figurka z masy cukrowej | 45 zł | postać, zwierzę albo pojazd, do 10 cm\n"
        "Napis czekoladowy | 15 zł | do 25 znaków"
    )
    sekcja = fragment_z(podziel_na_fragmenty(tekst), "Cennik dekoracji")

    assert "Figurka z masy cukrowej | 45 zł" in sekcja


def test_po_naglowku_dalszy_ciag_malej_litery_nie_tworzy_sekcji():
    tekst = (
        "Dostawa odbywa się w dni robocze.\n"
        "Krótka linia bez kropki\n"
        "która jest dalszym ciągiem zdania i ma ponad sześćdziesiąt znaków treści."
    )
    assert len(podziel_na_fragmenty(tekst)) == 1


def test_naglowek_z_numerem_jak_w_regulaminie():
    tekst = (
        "Zamówienie jest przyjęte po wpłacie zaliczki w wysokości 30% wartości.\n"
        "2. Anulowanie i zmiany\n"
        "Zamówienie można anulować bez utraty zaliczki najpóźniej 7 dni przed odbiorem.\n"
        "3. Dowóz\n"
        "Minimalna wartość zamówienia z dowozem to 150 zł, dowóz do 30 km gratis."
    )
    fragmenty = podziel_na_fragmenty(tekst)

    assert fragment_z(fragmenty, "2. Anulowanie").count("150 zł") == 0
    assert fragment_z(fragmenty, "3. Dowóz").startswith("3. Dowóz")


def test_znaki_sterujace_z_pdf_nie_trafiaja_do_tresci():
    assert not any("\x7f" in f for f in podziel_na_fragmenty(OFERTA_Z_PDF))


def test_tekst_z_pustymi_liniami_dzieli_sie_jak_dotad():
    tekst = (
        "NOCLEGI\n\nDysponujemy 14 pokojami dla 40 gości. Doba hotelowa 180 zł od pokoju.\n\n"
        "WESELA\n\nSala Dębowa mieści 120 osób. Cena w sobotę 4500 zł za salę z obsługą."
    )
    fragmenty = podziel_na_fragmenty(tekst)

    assert fragment_z(fragmenty, "NOCLEGI").count("Sala Dębowa") == 0
    assert fragment_z(fragmenty, "WESELA").count("Doba hotelowa") == 0


def _czas_podzialu(sekcji):
    sekcja = (
        "Nagłówek sekcji numer {}\n"
        "Treść sekcji z konkretami, cenami i opisem usługi, która ma ponad sześćdziesiąt znaków.\n"
    )
    tekst = "".join(sekcja.format(i) for i in range(sekcji))
    najkrotszy = float("inf")
    for _ in range(3):
        start = time.perf_counter()
        podziel_na_fragmenty(tekst)
        najkrotszy = min(najkrotszy, time.perf_counter() - start)
    return najkrotszy


def test_czas_podzialu_rosnie_liniowo():
    """
    Szukanie sąsiednich linii nie może być kwadratowe - limit to 2 mln znaków.

    Porównujemy tempo zamiast sztywnego progu w sekundach: CI bywa kilka razy
    wolniejsze od laptopa, a próg dość luźny dla CI przepuszczał wersję
    kwadratową. Czterokrotnie dłuższy tekst: liniowo ~4 razy dłużej,
    kwadratowo ~16.
    """
    maly, duzy = _czas_podzialu(5000), _czas_podzialu(20000)

    assert duzy / maly < 9


def test_spojniki_i_slowa_czasu_nie_sa_slowami_tematu():
    """Ten test padał przed 2.26.0: „jeśli" i „wcześniej" były wymagane od fragmentu."""
    assert slowa_kluczowe("Co jeśli odwołam przyjęcie 10 dni wcześniej?") == ["odwoł", "przyj"]
