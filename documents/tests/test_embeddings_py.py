import pytest
from unittest.mock import patch

from accounts.models import Tenant
from documents.models import DocumentChunk, Document


@pytest.mark.django_db
@patch("documents.utils.embedding_generator.generate_embeddings_for_document")
def test_embeddings_are_generated_for_chunks(mock_generate_embedding,tenant):
    mock_generate_embedding.return_value = [0.0] * 1536


    document = Document.objects.create(name="Doc", tenant=tenant, content="Test")

    chunk = DocumentChunk.objects.create(content="Test text", document=document, embedding=[0.0] * 1536)

    assert chunk.embedding is not None
