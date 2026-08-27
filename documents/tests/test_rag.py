from unittest.mock import MagicMock, patch

import pytest

from accounts.models import Tenant
from documents.models import Document, DocumentChunk


def stub_embedding(mock_client, vector=None):
    response = MagicMock()
    response.data = [MagicMock(embedding=vector or [0.0] * 1536)]
    mock_client.embeddings.create.return_value = response


@pytest.mark.django_db
@patch("rag.engine.client")
def test_query_chunks_respects_top_k(mock_client, tenant):
    stub_embedding(mock_client)

    doc = Document.objects.create(name="Doc", tenant=tenant, content="abc")
    for text in ["Witamy w regulaminie", "Polityka prywatności", "Jak zarejestrować konto"]:
        DocumentChunk.objects.create(document=doc, content=text, embedding=[0.0] * 1536)

    from rag.engine import query_similar_chunks_pgvector

    results = query_similar_chunks_pgvector(tenant.id, "rejestracja konta", top_k=2)

    assert len(results) == 2


@pytest.mark.django_db
@patch("rag.engine.client")
def test_query_chunks_never_leak_between_tenants(mock_client, tenant):
    """Fragmenty jednej firmy nie mogą trafić w kontekst odpowiedzi innej."""
    stub_embedding(mock_client)

    other = Tenant.objects.create(name="Obca firma", owner_email="obca@example.com")
    other_doc = Document.objects.create(name="Obcy", tenant=other, content="x")
    DocumentChunk.objects.create(document=other_doc, content="tajne dane", embedding=[0.0] * 1536)

    mine = Document.objects.create(name="Moj", tenant=tenant, content="y")
    DocumentChunk.objects.create(document=mine, content="moje dane", embedding=[0.0] * 1536)

    from rag.engine import query_similar_chunks_pgvector

    results = query_similar_chunks_pgvector(tenant.id, "cokolwiek", top_k=5)

    assert [c.content for c in results] == ["moje dane"]
