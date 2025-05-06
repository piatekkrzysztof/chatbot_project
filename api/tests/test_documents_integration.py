import pytest
from documents.models import Document
from unittest.mock import patch

@pytest.mark.django_db
@patch("api.views.documents.embed_document_task.delay")
def test_document_upload_dispatches_embedding_task(mock_embedding_task, api_client, tenant, valid_pdf_file):
    response = api_client.post(
        "/api/documents-upload/",
        {
            "name": "Test",
            "file": valid_pdf_file
        },
        format="multipart",
        HTTP_X_API_KEY=tenant.api_key
    )

    assert response.status_code == 201

    doc = Document.objects.get(name="Test")
    assert doc.content
    mock_embedding_task.assert_called_once_with(doc.id)
