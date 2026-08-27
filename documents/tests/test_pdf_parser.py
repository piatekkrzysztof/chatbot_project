"""
Wyciąganie tekstu z PDF-a.

Kategoria ryzyka: DOSTĘPNOŚĆ USŁUGI. Parser chodzi synchronicznie w żądaniu
HTTP (`api/views/documents.py`), a nie w zadaniu w tle - więc plik, który go
zapętli albo wyczerpie pamięć, blokuje wątek gunicorna, nie workera. Przy
czterech procesach po osiem wątków wystarczy kilkanaście takich plików, żeby
API przestało odpowiadać WSZYSTKIM najemcom.

Do 27 sierpnia 2026 ten kod nie miał żadnego testu: wszystkie testy wgrywania
dokumentów podmieniały `extract_text_from_pdf` atrapą. Zielony pakiet nie
mówił więc nic o tym, czy parser działa - wyszło to przy podnoszeniu pypdf
z 5.4.0 do 6.x, gdzie 855 przechodzących testów nie stanowiło żadnego dowodu.
"""

import io

import pytest

from documents.utils.pdf_parser import extract_text_from_pdf


def zbuduj_pdf(tekst: str) -> bytes:
    """
    Najmniejszy poprawny PDF zawierający jedną linijkę tekstu.

    Budowany tutaj, a nie wczytywany z pliku, celowo: repozytorium nie ma
    poprawnego PDF-a do testów (jedyny śledzony `documents/test.pdf` jest
    urwany), a plik binarny w repozytorium to fikstura, której nikt nie umie
    zmienić ani sprawdzić. Tu widać dokładnie, co jest w środku.

    Tablica `xref` wymaga bajtowych przesunięć każdego obiektu, więc liczymy
    je w trakcie składania - wpisane na sztywno rozjechałyby się przy pierwszej
    zmianie treści.
    """
    obiekty = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        None,  # strumień z treścią, składany niżej
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    strumien = f"BT /F1 12 Tf 20 100 Td ({tekst}) Tj ET".encode("latin-1")
    obiekty[3] = (
        b"<< /Length " + str(len(strumien)).encode() + b" >>\nstream\n" + strumien + b"\nendstream"
    )

    plik = bytearray(b"%PDF-1.4\n")
    przesuniecia = []
    for numer, tresc in enumerate(obiekty, start=1):
        przesuniecia.append(len(plik))
        plik += str(numer).encode() + b" 0 obj\n" + tresc + b"\nendobj\n"

    start_xref = len(plik)
    plik += b"xref\n0 " + str(len(obiekty) + 1).encode() + b"\n"
    plik += b"0000000000 65535 f \n"
    for przesuniecie in przesuniecia:
        plik += f"{przesuniecie:010d} 00000 n \n".encode()

    plik += b"trailer\n<< /Size " + str(len(obiekty) + 1).encode() + b" /Root 1 0 R >>\n"
    plik += b"startxref\n" + str(start_xref).encode() + b"\n%%EOF\n"
    return bytes(plik)


class TestPoprawnegoPliku:
    def test_wyciaga_tekst_ze_strony(self):
        plik = io.BytesIO(zbuduj_pdf("Rowerownia Krakowska"))

        assert "Rowerownia Krakowska" in extract_text_from_pdf(plik)

    def test_zwraca_napis_bez_otaczajacych_bialych_znakow(self):
        # Treść dokumentu trafia wprost do bazy wiedzy i dalej do porównań
        # wektorowych - niepotrzebne białe znaki na brzegach tylko zaszumiają.
        plik = io.BytesIO(zbuduj_pdf("Godziny otwarcia"))

        wynik = extract_text_from_pdf(plik)

        assert wynik == wynik.strip()


class TestZepsutegoPliku:
    """
    Uszkodzony PDF to nie przypadek brzegowy.

    Urwane pobieranie, plik ze skanera, dokument zapisany przez program, który
    się wysypał - użytkownik nie ma jak tego rozpoznać przed wgraniem. Widok
    ma odpowiedzieć czytelnie, a nie pięćsetką.
    """

    def test_urwany_plik_daje_wyjatek_parsera_a_nie_cisze(self):
        # Nie chodzi o to, żeby parser milczał: pusty napis w bazie wiedzy
        # wyglądałby jak poprawnie wczytany, pusty dokument. Ma być widać,
        # że się nie udało - obsługą zajmuje się warstwa wyżej.
        from pypdf.errors import PyPdfError

        urwany = io.BytesIO(zbuduj_pdf("Cokolwiek")[:120])

        with pytest.raises(PyPdfError):
            extract_text_from_pdf(urwany)

    def test_plik_ktory_wcale_nie_jest_pdfem(self):
        from pypdf.errors import PyPdfError

        with pytest.raises(PyPdfError):
            extract_text_from_pdf(io.BytesIO(b"to jest zwykly tekst, nie PDF"))
