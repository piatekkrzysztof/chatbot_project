import pytest
from unittest.mock import patch
from documents.models import DocumentChunk

@pytest.mark.django_db
@patch("documents.utils.embedding_generator.generate_embeddings_for_document")
def test_embeddings_are_generated_for_chunks(mock_generate_embedding):
    mock_generate_embedding.return_value = [0.0] * 1536

    chunk = DocumentChunk.objects.create(content="Test text", document_id=1)
    chunk.generate_embedding()

    mock_generate_embedding.assert_called_once_with("Test text")
    assert chunk.embedding is not None
