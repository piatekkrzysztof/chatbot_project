"""
Przeprowadzenie oceny: od korpusu do liczb.

Jedna ścieżka kodu dla obu zastosowań - pomiaru w CI na zamrożonych wektorach
i pomiaru na żywym modelu. Różni je wyłącznie to, skąd bierze się wektor
pytania. Gdyby były to dwie implementacje, ich wyniki przestałyby być
porównywalne przy pierwszej rozbieżności, a właśnie porównywalność jest
jedynym powodem, dla którego to istnieje.

Podstawiamy TYLKO liczenie wektora pytania. Całe wyszukiwanie - zapytanie do
pgvector, próg odległości, sortowanie, filtr wyłączonych dokumentów - jest
prawdziwe. Testowanie własnej atrapy zamiast silnika byłoby pomiarem niczego.
"""

import json
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock, patch

from accounts.models import Tenant
from documents.models import Document, DocumentChunk
from rag.engine import query_similar_chunks_pgvector
from rag.ocena.korpus import FRAGMENTY, PYTANIA, Pytanie
from rag.ocena.miary import Ocena, WynikPytania, policz

SCIEZKA_WZORCA = Path(__file__).resolve().parent / "wzorzec.json"


def wczytaj_wzorzec() -> dict:
    if not SCIEZKA_WZORCA.exists():
        raise FileNotFoundError(
            f"Brak wzorca {SCIEZKA_WZORCA}. Zbuduj go komenda: python manage.py zbuduj_wzorzec_rag"
        )
    return json.loads(SCIEZKA_WZORCA.read_text(encoding="utf-8"))


def zaloz_baze_wiedzy(wzorzec: dict) -> tuple[Tenant, dict[int, str]]:
    """
    Wstawia korpus do bazy jako prawdziwe dokumenty i fragmenty.

    Zwraca też mapowanie z identyfikatora fragmentu na jego klucz w korpusie -
    bez tego wyniki wyszukiwania byłyby listą tekstów, których trzeba by
    szukać po treści.
    """
    firma = Tenant.objects.create(name="Rowerownia (zestaw pomiarowy)")
    # processed=False celowo. Dokument oznaczony jako przetworzony, ktory nie
    # ma jeszcze fragmentow, odpala sygnal generowania embeddingow - a ten
    # dorabia WLASNE fragmenty przez OpenAI i zanieczyszcza pomiar cudzymi
    # wektorami. W pustej bazie testowej przechodzilo to niezauwazone;
    # wysypalo sie dopiero przy uruchomieniu komendy na bazie deweloperskiej.
    dokument = Document.objects.create(
        tenant=firma,
        name="Baza wiedzy do pomiaru",
        content="\n".join(FRAGMENTY.values()),
        processed=False,
    )

    po_id = {}
    for klucz, tresc in FRAGMENTY.items():
        fragment = DocumentChunk.objects.create(
            document=dokument,
            content=tresc,
            embedding=wzorzec["fragmenty"][klucz],
        )
        po_id[fragment.id] = klucz

    return firma, po_id


def przebiegnij(
    firma: Tenant,
    po_id: dict[int, str],
    wektor_pytania: Callable[[Pytanie], list[float]],
    top_k: int = 5,
    max_distance: float | None = None,
) -> list[WynikPytania]:
    """
    Zadaje każde pytanie z korpusu i zbiera, co wróciło.

    `wektor_pytania` jest jedynym miejscem, które różni pomiar w CI od pomiaru
    na żywym modelu.
    """
    wyniki = []

    for pytanie in PYTANIA:
        odpowiedz = MagicMock()
        odpowiedz.data = [MagicMock(embedding=wektor_pytania(pytanie))]

        with patch("rag.engine.client") as klient:
            klient.embeddings.create.return_value = odpowiedz
            fragmenty = query_similar_chunks_pgvector(
                firma.id, pytanie.tresc, top_k=top_k, max_distance=max_distance
            )

        wyniki.append(
            WynikPytania(
                pytanie=pytanie,
                znalezione=tuple(po_id[f.id] for f in fragmenty),
            )
        )

    return wyniki


def ocen_na_wzorcu(top_k: int = 5, max_distance: float | None = None) -> tuple[Ocena, list]:
    """
    Pomiar na zamrożonych wektorach - bez ani jednego wywołania API.

    Zwraca ocenę i surowe wyniki, żeby wywołujący mógł wypisać, co konkretnie
    poszło nie tak. Sama liczba mówi, że jest gorzej, nie mówi czemu.
    """
    wzorzec = wczytaj_wzorzec()
    firma, po_id = zaloz_baze_wiedzy(wzorzec)

    wyniki = przebiegnij(
        firma,
        po_id,
        wektor_pytania=lambda pytanie: wzorzec["pytania"][pytanie.tresc],
        top_k=top_k,
        max_distance=max_distance,
    )
    return policz(wyniki), wyniki
