import io
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from documents.models import Document, DocumentChunk
from accounts.models import Tenant, CustomUser
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


@pytest.mark.django_db
def test_list_chunks_for_document():
    tenant = Tenant.objects.create(name="Firma A", api_key="abc123")
    user = CustomUser.objects.create_user(username="a", email="a@x.com", password="x", tenant=tenant)
    doc = Document.objects.create(name="Doc", tenant=tenant, processed=True)
    for i in range(5):
        DocumentChunk.objects.create(document=doc, content=f"chunk {i}", embedding=[0.1] * 1536)

    client = APIClient()
    client.force_authenticate(user=user)
    url = reverse("document-chunks", args=[doc.id])
    res = client.get(url, HTTP_X_API_KEY="abc123")
    assert res.status_code == 200
    assert len(res.data) == 5