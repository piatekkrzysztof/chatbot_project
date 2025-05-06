import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from documents.models import Document
from documents.models import DocumentChunk
from unittest.mock import patch


@pytest.mark.django_db
@patch("documents.tasks.generate_embeddings_for_document.delay")
def test_document_upload_creates_chunks_and_embeddings(mock_embedding_task, api_client, tenant):
    test_file = SimpleUploadedFile("test.pdf", b"Test content for PDF", content_type="application/pdf")

    response = api_client.post("/api/documents-upload/", {
        "name": "Test Document",
        "file": test_file
    }, HTTP_X_API_KEY=tenant.api_key)

    assert response.status_code == 201

    doc = Document.objects.get(name="Test Document")
    chunks = DocumentChunk.objects.filter(document=doc)

    assert chunks.exists()
    assert mock_embedding_task.called