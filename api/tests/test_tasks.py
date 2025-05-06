import pytest
from unittest.mock import patch, MagicMock
from documents.models import Document, DocumentChunk
from documents.tasks import generate_embeddings_for_document


@pytest.mark.django_db
@patch("documents.tasks.chromadb.Client")
@patch("documents.tasks.OpenAIEmbeddingFunction")
def test_generate_embeddings_for_document_creates_chunks(mock_embedding_fn_class, mock_chroma_client, tenant):
    # 🔧 Mock OpenAI embedding function (zwraca listę 1D floatów)
    mock_embedding_fn = MagicMock()
    mock_embedding_fn.return_value = [0.01] * 1536
    mock_embedding_fn_class.return_value = mock_embedding_fn

    # 🔧 Mock ChromaDB
    mock_chroma_collection = MagicMock()
    mock_chroma_client.return_value.get_or_create_collection.return_value = mock_chroma_collection

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

    # ✅ Sprawdź, czy Chroma została zawołana
    assert mock_chroma_collection.add.called
