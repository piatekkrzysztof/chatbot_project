"""
Wymiar wektora musi się zgadzać w czterech miejscach naraz.

Kategoria ryzyka: RDZEŃ PRODUKTU. Wymiar jest zapisany w schemacie bazy,
w stałej w kodzie, w każdym wywołaniu API embeddingów i w zamrożonym wzorcu
oceny. Rozjazd między którymikolwiek dwoma z nich psuje wyszukiwanie, a każdy
rozjazd psuje je inaczej:

  kolumna kontra API      - błąd przy zapisie, bot nie dostaje nowej wiedzy
  zapytanie kontra kolumna - błąd przy każdym pytaniu, bot milczy
  wzorzec kontra kolumna   - ocena mierzy inny produkt niż ten wdrożony

Tylko trzeci jest cichy, i dlatego jest najgorszy: testy jakości dalej
świecą na zielono, opisując wyszukiwanie, którego nikt nie uruchomił.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.db import DataError, connection, transaction

from accounts.models import Tenant
from documents.models import Document, DocumentChunk
from documents.wymiar import WYMIAR_WEKTORA

pytestmark = pytest.mark.django_db


@pytest.fixture
def dokument():
    firma = Tenant.objects.create(name="Firma od wymiaru")
    return Document.objects.create(
        tenant=firma,
        name="Cennik",
        content="Przeglad podstawowy 120 zl.",
        # processed=False, zeby nie odpalic sygnalu liczacego wektory.
        processed=False,
    )


class TestSchematuBazy:
    """
    Kolumna w bazie, nie deklaracja w Pythonie.

    `VectorField(dimensions=...)` mowi tylko, co Django SADZI o kolumnie.
    Prawdziwa szerokosc ustawila migracja i to ona rozstrzyga, wiec ten test
    pyta baze, a nie model. Stala zmieniona bez migracji przechodzi kazdy
    test, ktory patrzy wylacznie w kod.
    """

    def test_kolumna_przyjmuje_wektor_o_zadeklarowanej_dlugosci(self, dokument):
        fragment = DocumentChunk.objects.create(
            document=dokument, content="tresc", embedding=[0.1] * WYMIAR_WEKTORA
        )

        fragment.refresh_from_db()
        assert len(fragment.embedding) == WYMIAR_WEKTORA

    def test_kolumna_odrzuca_wektor_o_innej_dlugosci(self, dokument):
        """
        Druga strona. Bez tego test wyzej przeszedlby takze wtedy, gdyby
        kolumna byla szersza niz stala - a wtedy do bazy wchodzilyby wektory
        dwoch roznych dlugosci i odleglosci przestalyby byc porownywalne.
        """
        with pytest.raises(DataError), transaction.atomic():
            DocumentChunk.objects.create(
                document=dokument, content="tresc", embedding=[0.1] * (WYMIAR_WEKTORA + 1)
            )

    def test_typ_kolumny_nazywa_ten_sam_wymiar(self):
        # Komunikat z samego Postgresa. Gdy sie rozjedzie, blad ma powiedziec
        # WPROST, ile wynosi jedno i drugie - "expected 512 dimensions" bez
        # informacji, skad wzielo sie 512, kaze szukac po omacku.
        with connection.cursor() as kursor:
            kursor.execute(
                """
                SELECT format_type(atttypid, atttypmod)
                FROM pg_attribute
                WHERE attrelid = 'documents_documentchunk'::regclass
                  AND attname = 'embedding'
                """
            )
            typ = kursor.fetchone()[0]

        assert typ == f"vector({WYMIAR_WEKTORA})", (
            f"Kolumna embedding ma typ {typ}, a documents/wymiar.py mowi "
            f"{WYMIAR_WEKTORA}. Brakuje migracji albo stala zostala zmieniona "
            f"bez niej."
        )


class TestWywolanApi:
    """
    Model liczy 1536 liczb, dopoki nie powie mu sie inaczej.

    `dimensions` nie jest optymalizacja, tylko warunkiem poprawnosci: bez tego
    parametru API oddaje domyslna dlugosc, ktora do kolumny nie wejdzie.
    Sprawdzamy oba kierunki osobno, bo to dwa rozne pliki i jeden da sie
    poprawic, zapominajac o drugim.
    """

    def test_zapis_fragmentow_prosi_o_wlasciwa_dlugosc(self, dokument, monkeypatch):
        import documents.utils.embedding_generator as generator

        klient = MagicMock()
        # Wektor o dlugosci, o ktora kod poprosil - nie o zadeklarowanej.
        # Gdyby prosil o zla, zapis do bazy padnie i test powie o tym wprost,
        # zamiast przejsc na wektorze podstawionym z wlasciwa dlugoscia.
        klient.embeddings.create.side_effect = lambda model, input, dimensions: MagicMock(
            data=[MagicMock(index=i, embedding=[0.01] * dimensions) for i in range(len(input))]
        )
        monkeypatch.setattr(generator, "get_client", lambda tenant=None: klient)

        generator.generate_embeddings_for_document(dokument)

        assert klient.embeddings.create.call_args.kwargs["dimensions"] == WYMIAR_WEKTORA

    def test_pytanie_prosi_o_wlasciwa_dlugosc(self, dokument):
        from rag.engine import query_similar_chunks_pgvector

        DocumentChunk.objects.create(
            document=dokument, content="tresc", embedding=[0.0] * WYMIAR_WEKTORA
        )

        with patch("rag.engine.client") as klient:
            klient.embeddings.create.return_value = MagicMock(
                data=[MagicMock(embedding=[0.0] * WYMIAR_WEKTORA)]
            )
            query_similar_chunks_pgvector(dokument.tenant_id, "ile kosztuje przeglad?")

        assert klient.embeddings.create.call_args.kwargs["dimensions"] == WYMIAR_WEKTORA
