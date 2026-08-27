import pytest
from unittest.mock import patch, MagicMock
from documents.models import Document, DocumentChunk
from documents.tasks import generate_embeddings_for_document


@pytest.mark.django_db
# Bylo "…embedding_generator.client" — nazwa, ktorej ten modul nie ma od czasu,
# gdy dostal fabryke get_client(tenant). Mock nie trafial wiec w nic, a kod
# wolal PRAWDZIWE API OpenAI: lokalnie test przechodzil (bo lokalnie jest
# klucz) i po cichu kosztowal przy kazdym przebiegu, a w CI wywracal caly
# suite bledem polaczenia.
@patch("documents.utils.embedding_generator.get_client")
def test_generate_embeddings_for_document_creates_chunks(mock_get_client, tenant):
    # Fabryka zwraca klienta, wiec mockujemy fabryke i podstawiamy klienta.
    mock_response = MagicMock()
    # Kod sortuje odpowiedz po `index`, wiec atrapa musi go miec.
    mock_response.data = [MagicMock(embedding=[0.01] * 1536, index=0)]
    mock_openai_client = MagicMock()
    mock_openai_client.embeddings.create.return_value = mock_response
    mock_get_client.return_value = mock_openai_client

    # 📄 Dokument testowy
    doc = Document.objects.create(
        tenant=tenant, name="Test Doc", content="Chunk A. Chunk B. Chunk C." * 100
    )

    # 🔁 Uruchom zadanie
    generate_embeddings_for_document(doc.id)

    # ✅ Sprawdź, czy powstały chunki
    chunks = DocumentChunk.objects.filter(document=doc)
    assert chunks.exists()
    assert all(len(c.embedding) == 1536 for c in chunks)
