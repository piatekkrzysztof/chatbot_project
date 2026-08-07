import pytest
from unittest.mock import patch, MagicMock
from documents.models import Document, DocumentChunk
from documents.tasks import generate_embeddings_for_document


@pytest.mark.django_db
@patch("documents.utils.embedding_generator.client")
def test_generate_embeddings_for_document_creates_chunks(mock_openai_client, tenant):
    # 🔧 Mock OpenAI embeddings API (zwraca listę 1D floatów)
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.01] * 1536)]
    mock_openai_client.embeddings.create.return_value = mock_response

    # 📄 Dokument testowy
    doc = Document.objects.create(
        tenant=tenant,
        name="Test Doc",
        content="Chunk A. Chunk B. Chunk C." * 100
    )

    # 🔁 Uruchom zadanie
    generate_embeddings_for_document(doc.id)

    # ✅ Sprawdź, czy powstały chunki
    chunks = DocumentChunk.objects.filter(document=doc)
    assert chunks.exists()
    assert all(len(c.embedding) == 1536 for c in chunks)
