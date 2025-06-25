import io
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from documents.models import Document, DocumentChunk
from accounts.models import Tenant, CustomUser
from rest_framework.test import APIClient
from reportlab.pdfgen import canvas


def generate_valid_pdf_bytes():
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer)
    p.drawString(100, 750, "Test PDF content")
    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer


@pytest.mark.django_db
def test_document_upload_creates_chunks(monkeypatch,user, tenant, subscribtion):
    from documents.tasks import embed_document_task
    monkeypatch.setattr(embed_document_task, "delay", lambda *args, **kwargs: None)

    client = APIClient()
    user.tenant = tenant
    user.role = "owner"
    user.save()
    tenant.save()
    client.force_authenticate(user=user)

    pdf = generate_valid_pdf_bytes()
    pdf.name = "test.pdf"

    response = client.post(
        "/api/documents-upload/",
        {"file": pdf, "name": "Test"},
        format="multipart",
        HTTP_X_API_KEY=str(tenant.api_key)
    )

    assert response.status_code == 201
    assert Document.objects.count() == 1


@pytest.mark.django_db
def test_list_chunks_for_document(user, tenant, subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.role = "owner"
    user.save()
    tenant.save()
    client.force_authenticate(user=user)

    doc = Document.objects.create(name="Doc", tenant=tenant, processed=True)
    for i in range(5):
        DocumentChunk.objects.create(document=doc, content=f"chunk {i}", embedding=[0.1] * 1536)

    url = reverse("document-chunks", args=[doc.id])
    res = client.get(url, HTTP_X_API_KEY=str(tenant.api_key))

    assert res.status_code == 200
    assert len(res.data) == 5


@pytest.mark.django_db
def test_upload_without_file_returns_400(user, tenant, subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.role = "owner"
    user.save()
    tenant.save()
    client.force_authenticate(user=user)
    response = client.post(
        "/api/documents-upload/",
        data={"name": "Test"},
        HTTP_X_API_KEY=str(tenant.api_key)
    )
    assert response.status_code == 400
    assert "error" in response.data or "file" in response.data


@pytest.mark.django_db
def test_chunk_list_nonexistent_document_returns_empty(user, tenant, subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.role = "owner"
    user.save()
    tenant.save()
    client.force_authenticate(user=user)
    url = reverse("document-chunks", args=[9999])  # nieistniejący ID
    res = client.get(url, HTTP_X_API_KEY=str(tenant.api_key))
    assert res.status_code == 200
    assert res.data == []


@pytest.mark.django_db
def test_document_detail_view_response_fields(user, tenant, subscribtion):
    user.tenant = tenant
    user.role = "owner"
    user.save()
    tenant.save()
    doc = Document.objects.create(name="Doc", tenant=tenant, processed=True, content="abc def")
    client = APIClient()
    client.force_authenticate(user=user)
    url = reverse("document-detail", args=[doc.id])
    res = client.get(url, HTTP_X_API_KEY=str(tenant.api_key))
    assert res.status_code == 200
    for field in ["id", "name", "processed", "uploaded_at", "chunk_count", "status", "preview"]:
        assert field in res.data


@pytest.mark.django_db
def test_missing_api_key_returns_403_on_upload(user, tenant, subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.role = "owner"
    user.save()
    tenant.save()
    client.force_authenticate(user=user)
    response = APIClient().post("/api/documents-upload/", HTTP_X_API_KEY=str(tenant.api_key))
    assert response.status_code == 403
