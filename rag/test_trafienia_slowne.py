"""
Cennik w tabeli i dopasowanie po słowach - 2.25.0.

Kategoria ryzyka: CENA JEST W DOKUMENCIE, A BOT JEJ NIE ZNA. Odbiór 7.10.2026:
cennik z DOCX trafiał do jednego fragmentu i pytanie o jedną pozycję leżało za
progiem - bot odpowiadał „nie posiadam informacji". Pomiar na prawdziwych
embeddingach: przed poprawką 4 z 8 pytań o pozycje, po poprawce 8 z 8, cisza
bez zmian.

Wektory są tu ułożone ręcznie, żeby odległość była dokładnie taka, jakiej
potrzebuje przypadek. Zapytanie do pgvector, filtr firmy i dokumentów są
prawdziwe.
"""

import math
from unittest.mock import MagicMock, patch

import pytest

from documents.models import Document, DocumentChunk
from documents.utils.fragmenty import fragmenty_wierszy_tabel, podziel_na_fragmenty
from documents.wymiar import WYMIAR_WEKTORA
from rag.engine import (
    MAKS_ODLEGLOSC_SLOWNA,
    MAKS_TRAFIEN_SLOWNYCH,
    query_similar_chunks_pgvector,
    slowa_kluczowe,
)

pytestmark = pytest.mark.django_db

PYTANIE = [1.0] + [0.0] * (WYMIAR_WEKTORA - 1)


def w_odleglosci(odleglosc, os=1):
    """Wektor jednostkowy o zadanej odległości L2 od wektora pytania."""
    a = 1 - odleglosc**2 / 2
    wektor = [0.0] * WYMIAR_WEKTORA
    wektor[0], wektor[os] = a, math.sqrt(1 - a**2)
    return wektor


def odpowiedz(wektor):
    odp = MagicMock()
    odp.data = [MagicMock(embedding=wektor)]
    return odp


@pytest.fixture
def dokument(tenant):
    return Document.objects.create(tenant=tenant, name="cennik.docx", content="x", processed=False)


def fragment(dokument, tresc, odleglosc, os=1):
    return DocumentChunk.objects.create(
        document=dokument, content=tresc, embedding=w_odleglosci(odleglosc, os)
    )


def szukaj(tenant, pytanie):
    with patch("rag.engine.client") as klient:
        klient.embeddings.create.return_value = odpowiedz(PYTANIE)
        return query_similar_chunks_pgvector(tenant.id, pytanie)


def test_slowo_z_pytania_ratuje_fragment_za_progiem(tenant, dokument):
    """Ten test padał przed 2.25.0: wiersz o 1,03 był odcinany progiem 0,96."""
    zlocenia = fragment(dokument, "Usługa | Cena\nZłocenia płatkowym złotem | 60 zł", 1.03)
    fragment(dokument, "Usługa | Cena\nNapis czekoladowy | 15 zł", 1.03, os=2)

    wyniki = szukaj(tenant, "Macie złocenia? Ile to kosztuje?")

    assert [f.pk for f in wyniki] == [zlocenia.pk]


def test_wymaga_wszystkich_slow_tematu(tenant, dokument):
    """„Serwis" w godzinach otwarcia nie odpowiada na pytanie o serwis amortyzatorów."""
    fragment(dokument, "Serwis czynny od poniedziałku do piątku 9-17.", 1.0)

    assert szukaj(tenant, "Serwis amortyzatorów powietrznych - robicie?") == []


def test_za_daleko_mimo_slow(tenant, dokument):
    fragment(dokument, "Złocenia płatkowym złotem | 60 zł", MAKS_ODLEGLOSC_SLOWNA + 0.05)

    assert szukaj(tenant, "Macie złocenia?") == []


def test_odmiana_slowa_nie_przeszkadza(tenant, dokument):
    """Polskie końcówki: „wypożyczacie" w pytaniu, „wypożyczenie" w cenniku."""
    stojak = fragment(dokument, "Stojak trzypiętrowy | 50 zł | wypożyczenie, zwrot do 3 dni", 1.0)

    assert [f.pk for f in szukaj(tenant, "Czy wypożyczacie stojak na tort?")] == [stojak.pk]


def test_trafienia_wektorowe_zostaja_obok_slownych(tenant, dokument):
    """Słowa dostają co najwyżej dwa miejsca; reszta to dotychczasowe wyniki."""
    blisko = [fragment(dokument, f"Tort numer {i}", 0.5 + i / 100, os=2 + i) for i in range(5)]
    slowne = [
        fragment(dokument, f"Złocenia wariant {i}", 1.0 + i / 100, os=10 + i) for i in range(3)
    ]

    wyniki = szukaj(tenant, "Macie złocenia?")

    assert len(wyniki) == 5
    assert {f.pk for f in wyniki} == {f.pk for f in blisko[:3]} | {f.pk for f in slowne[:2]}
    assert MAKS_TRAFIEN_SLOWNYCH == 2


def test_wylaczony_dokument_nie_wraca_przez_slowa(tenant, dokument):
    """Dopasowanie po słowach idzie przez ten sam filtr, co wyszukiwanie wektorowe."""
    fragment(dokument, "Złocenia płatkowym złotem | 60 zł", 1.0)
    Document.objects.filter(pk=dokument.pk).update(uzywaj_w_wyszukiwaniu=False)

    assert szukaj(tenant, "Macie złocenia?") == []


def test_obca_firma_nie_wraca_przez_slowa(tenant, dokument):
    from accounts.models import Tenant

    obca = Tenant.objects.create(name="Obca", owner_email="o@example.com")
    fragment(dokument, "Złocenia płatkowym złotem | 60 zł", 1.0)

    assert szukaj(obca, "Macie złocenia?") == []


def test_slowa_kluczowe_pomijaja_slowa_pytajace():
    assert slowa_kluczowe("Ile kosztuje figurka z masy cukrowej?") == ["figur", "cukro"]
    assert slowa_kluczowe("Jakie kwiaty jadalne macie?") == ["kwiat", "jadal"]
    assert slowa_kluczowe("Dzień dobry") == []


# --- Podział tabel ----------------------------------------------------------------

CENNIK_Z_DOCX = """Cukiernia - cennik dekoracji
Ceny brutto.
Usługa | Cena | Uwagi
Figurka z masy cukrowej | 45 zł | do 10 cm
Napis czekoladowy | 15 zł | do 25 znaków
Złocenia płatkowym złotem | 60 zł | jadalne złoto
Zniżki: trzecia dekoracja gratis."""


def test_kazdy_wiersz_tabeli_ma_wlasny_fragment_z_naglowkiem():
    """Ten test padał przed 2.25.0: cała tabela była jednym fragmentem."""
    fragmenty = podziel_na_fragmenty(CENNIK_Z_DOCX)

    assert "Usługa | Cena | Uwagi\nFigurka z masy cukrowej | 45 zł | do 10 cm" in fragmenty
    assert "Usługa | Cena | Uwagi\nZłocenia płatkowym złotem | 60 zł | jadalne złoto" in fragmenty
    # Cała tabela zostaje - pytanie o cały cennik działa jak dotąd.
    assert any("Figurka" in f and "Złocenia" in f for f in fragmenty)


def test_tabela_markdown_bez_linii_separatora():
    tekst = (
        "| Pakiet | Netto | Brutto |\n|---|---:|---:|\n"
        "| S | 99 zł | 122 zł |\n| M | 199 zł | 245 zł |"
    )

    assert fragmenty_wierszy_tabel(tekst) == [
        "Pakiet | Netto | Brutto\nS | 99 zł | 122 zł",
        "Pakiet | Netto | Brutto\nM | 199 zł | 245 zł",
    ]


@pytest.mark.parametrize(
    "tekst",
    [
        "Zwykły akapit bez tabeli.\n\nDrugi akapit.",
        "Telefon | e-mail\nwyłącznie jedna linia danych | x",  # nagłówek i jeden wiersz
        "Godziny | 9-17\nSobota | 10-14 | zamknięte w święta",  # różna liczba kolumn
    ],
)
def test_bez_tabeli_nie_ma_dodatkowych_fragmentow(tekst):
    assert fragmenty_wierszy_tabel(tekst) == []
