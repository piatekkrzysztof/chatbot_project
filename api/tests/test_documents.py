import io
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from documents.models import Document, DocumentChunk
from accounts.models import Tenant
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_document_upload_creates_chunks():
    tenant = Tenant.objects.create(name="TestOrg", owner_email="admin@test.com")
    client = APIClient()

    pdf_content = b"%PDF-1.4 example content"  # przykładowy PDF
    test_pdf = SimpleUploadedFile("test.pdf", pdf_content, content_type="application/pdf")

    response = client.post(
        "/api/documents-upload/",
        {"file": test_pdf, "name": "Test PDF"},
        format="multipart",
        HTTP_X_API_KEY=tenant.api_key
    )

    assert response.status_code == 201
    assert Document.objects.count() == 1

    doc = Document.objects.first()

    # ⚠️ Jeśli używasz Celery, chunki mogą się jeszcze nie pojawić
    # Więc jeśli to test bez Celery = OK
    chunks = DocumentChunk.objects.filter(document=doc)
    assert chunks.exists()  # chunki istnieją?