import pytest

from accounts.models import Tenant
from documents.models import Document, DocumentChunk


@pytest.mark.django_db
def test_query_chunks_with_pgvector(monkeypatch):
    from rag.engine import query_similar_chunks_pgvector
    tenant = Tenant.objects.create(name="T", api_key="key")
    doc = Document.objects.create(name="Doc", tenant=tenant, content="abc")
    for text in ["Witamy w regulaminie", "Polityka prywatności", "Jak zarejestrować konto"]:
        DocumentChunk.objects.create(document=doc, content=text, embedding=[0.0]*1536)

    # mock embedding
    monkeypatch.setattr("openai.Embedding.create", lambda **kwargs: {"data": [{"embedding": [0.0]*1536}]})

    results = query_similar_chunks_pgvector(tenant.id, "rejestracja konta", top_k=2)
    assert len(results) == 2