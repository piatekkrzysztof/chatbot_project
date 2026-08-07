from unittest.mock import MagicMock, patch

import pytest

from documents.models import Document, DocumentChunk


def fake_embedding_response(vector):
    response = MagicMock()
    response.data = [MagicMock(embedding=vector)]
    return response


@pytest.mark.django_db
@patch("rag.engine.client")
def test_query_chunks_with_pgvector(mock_client, tenant):
    """Wyszukiwanie zwraca najbliższe fragmenty, bez odpytywania prawdziwego API."""
    mock_client.embeddings.create.return_value = fake_embedding_response([0.0] * 1536)

    doc = Document.objects.create(name="Doc", tenant=tenant, content="abc")
    for text in ["Witamy w regulaminie", "Polityka prywatności", "Jak zarejestrować konto"]:
        DocumentChunk.objects.create(document=doc, content=text, embedding=[0.0] * 1536)

    from rag.engine import query_similar_chunks_pgvector
    results = query_similar_chunks_pgvector(tenant.id, "rejestracja konta", top_k=2)

    assert len(results) == 2


@pytest.mark.django_db
@patch("rag.engine.client")
def test_distant_chunks_are_filtered_out(mock_client, tenant):
    """
    Fragmenty powyżej progu odległości nie mogą wracać — inaczej każde pytanie
    wyglądałoby na pokryte dokumentami, nawet zupełnie niezwiązanymi.
    """
    mock_client.embeddings.create.return_value = fake_embedding_response([1.0] + [0.0] * 1535)

    doc = Document.objects.create(name="Doc", tenant=tenant, content="abc")
    # wektor odległy od zapytania o 2.0 w metryce L2 — powyżej progu
    DocumentChunk.objects.create(document=doc, content="cos zupelnie innego",
                                 embedding=[-1.0] + [0.0] * 1535)

    from rag.engine import query_similar_chunks_pgvector
    results = query_similar_chunks_pgvector(tenant.id, "pytanie", top_k=5)

    assert results == []
