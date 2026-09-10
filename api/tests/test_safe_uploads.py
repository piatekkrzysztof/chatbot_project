"""Reject untrusted files before storing them or scheduling paid processing."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from documents.models import Document


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["price.txt", "price.md", "price.docx", "price.pdf"])
def test_valid_upload_is_parsed_once_before_embedding(upload_client, tenant, name, mocker):
    from documents.tests.test_file_storage import pdf_bytes
    from documents.tests.test_isolated_uploads import docx

    body = (
        docx()
        if name.endswith("docx")
        else pdf_bytes("Oferta 120 zl")
        if name.endswith("pdf")
        else b"Oferta 120 zl"
    )
    queue = mocker.patch("documents.signals.enqueue")
    result = upload_client.post(
        "/api/documents-upload/", {"file": SimpleUploadedFile(name, body)}, format="multipart"
    )
    assert result.status_code == 201
    document = Document.objects.get(tenant=tenant)
    assert document.processed
    assert "120" in document.content
    queue.assert_called_once()
    assert queue.call_args.args[0].name == "documents.tasks.generate_embeddings_for_document"


@pytest.mark.django_db
def test_rejected_document_never_reaches_storage_or_queue(upload_client, mocker):
    store = mocker.patch("documents.storage.DocumentStorage._save")
    queue = mocker.patch("documents.signals.enqueue")
    result = upload_client.post(
        "/api/documents-upload/",
        {"file": SimpleUploadedFile("fake.pdf", b"%PDF-1.4 broken")},
        format="multipart",
    )
    assert result.status_code == 400
    assert "PDF" in result.data["error"]
    store.assert_not_called()
    queue.assert_not_called()


@pytest.mark.django_db
def test_duplicate_file_field_is_rejected(upload_client, tenant):
    result = upload_client.post(
        "/api/documents-upload/",
        {"file": [SimpleUploadedFile("a.txt", b"a"), SimpleUploadedFile("b.txt", b"b")]},
        format="multipart",
    )
    assert result.status_code == 413
    assert not Document.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_overflow_cleans_temporary_upload(upload_client, settings, tmp_path):
    settings.FILE_UPLOAD_MAX_MEMORY_SIZE = 0
    settings.FILE_UPLOAD_TEMP_DIR = str(tmp_path)
    settings.DOCUMENT_MAX_UPLOAD_BYTES = 32
    response = upload_client.post(
        "/api/documents-upload/",
        {"file": SimpleUploadedFile("too-large.txt", b"x" * 64)},
        format="multipart",
    )
    assert response.status_code == 413
    assert list(tmp_path.iterdir()) == []


def test_declared_oversize_is_rejected_before_read(settings):
    from django.core.files.uploadhandler import StopUpload
    from django.test import RequestFactory

    from documents.uploads import LimitedUploadHandler

    request = RequestFactory().post("/api/documents-upload/")
    handler = LimitedUploadHandler(request)
    with pytest.raises(StopUpload):
        handler.handle_raw_input(None, {}, 11 * 1024 * 1024, b"boundary")


@pytest.mark.django_db
def test_text_field_cannot_impersonate_a_file(upload_client):
    result = upload_client.post("/api/documents-upload/", {"file": "fake.txt"}, format="multipart")
    assert result.status_code == 400


@pytest.mark.django_db
def test_background_knowledge_limit_preserves_existing_content(upload_client, tenant, mocker):
    from rest_framework.exceptions import ValidationError

    from documents.tasks import extract_text_from_document

    document = Document.objects.create(
        tenant=tenant,
        name="test",
        content="old",
        file=SimpleUploadedFile("test.txt", b"new content"),
    )
    mocker.patch("documents.tasks.sprawdz_limit_bazy_wiedzy", side_effect=ValidationError("limit"))
    queue = mocker.patch("documents.signals.enqueue")
    extract_text_from_document(document.id)
    document.refresh_from_db()
    assert document.content == "old"
    assert not document.processed
    assert "limit bazy wiedzy" in document.processing_error
    queue.assert_not_called()


@pytest.mark.django_db
def test_busy_parser_does_not_persist_document(upload_client, tenant):
    from documents.isolated_parser import parser_slot

    with parser_slot():
        result = upload_client.post(
            "/api/documents-upload/",
            {"file": SimpleUploadedFile("a.txt", b"a")},
            format="multipart",
        )
    assert result.status_code == 503
    assert not Document.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_valid_branding_and_invalid_second_image_are_atomic(upload_client, tenant):
    from documents.tests.test_isolated_uploads import picture

    result = upload_client.patch(
        "/api/widget-settings/mine/",
        {
            "widget_logo": SimpleUploadedFile("logo.png", picture()),
            "widget_avatar": SimpleUploadedFile("avatar.png", b"not an image"),
        },
        format="multipart",
    )
    assert result.status_code == 400
    tenant.refresh_from_db()
    assert not tenant.widget_logo
    assert not tenant.widget_avatar
    result = upload_client.patch(
        "/api/widget-settings/mine/",
        {
            "widget_logo": SimpleUploadedFile("logo.jpeg", picture("JPEG") + b"private_marker"),
        },
        format="multipart",
    )
    assert result.status_code == 200
    tenant.refresh_from_db()
    assert tenant.widget_logo.name.endswith(".png")
    with tenant.widget_logo.open("rb") as handle:
        assert b"private_marker" not in handle.read()


@pytest.mark.django_db
def test_failed_background_parse_has_consistent_status(upload_client, tenant, mocker):
    from api.serializers import DocumentSerializer
    from documents.tasks import extract_text_from_document

    document = Document.objects.create(
        tenant=tenant, name="broken", file=SimpleUploadedFile("broken.pdf", b"not a PDF")
    )
    queue = mocker.patch("documents.signals.enqueue")
    extract_text_from_document(document.id)
    document.refresh_from_db()
    assert not document.processed
    assert document.processing_error
    assert DocumentSerializer(document).data["status"] == "failed"
    result = upload_client.get(f"/api/documents/{document.id}/")
    assert result.status_code == 200
    assert result.data["status"] == "failed"
    assert result.data["processing_error"] == document.processing_error
    queue.assert_not_called()


@pytest.mark.django_db
def test_background_storage_error_is_sanitized(upload_client, tenant, mocker, caplog):
    from documents.tasks import extract_text_from_document

    document = Document.objects.create(
        tenant=tenant, name="test", file=SimpleUploadedFile("test.txt", b"content")
    )
    mocker.patch(
        "documents.storage.DocumentStorage.size", side_effect=OSError("private-provider-secret")
    )
    extract_text_from_document(document.id)
    document.refresh_from_db()
    assert document.processing_error
    assert "private-provider-secret" not in document.processing_error
    assert "private-provider-secret" not in caplog.text


@pytest.mark.django_db
def test_legacy_file_size_is_checked_before_downloading(upload_client, tenant, mocker):
    from documents.file_limits import MAX_DOCUMENT_BYTES
    from documents.tasks import extract_text_from_document

    document = Document.objects.create(
        tenant=tenant, name="test", file=SimpleUploadedFile("test.txt", b"content")
    )
    mocker.patch("documents.storage.DocumentStorage.size", return_value=MAX_DOCUMENT_BYTES + 1)
    opening = mocker.patch("documents.storage.DocumentStorage._open")
    extract_text_from_document(document.id)
    document.refresh_from_db()
    assert "10 MiB" in document.processing_error
    opening.assert_not_called()


@pytest.fixture
def upload_client(user, tenant, subscribtion, settings, tmp_path):
    settings.STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(tmp_path / "public")},
        },
        "private_documents": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(tmp_path / "private")},
        },
    }
    user.role = "owner"
    user.save()
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
    return client


@pytest.mark.django_db
@pytest.mark.parametrize(
    "name,body,mime",
    [
        ("payload.html", b"<script>alert(1)</script>", "text/html"),
        ("payload.exe", b"MZbinary", "application/pdf"),
        ("invoice.pdf.exe", b"MZbinary", "application/pdf"),
        (
            "fake.docx",
            b"not a ZIP document",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        ("binary.txt", b"MZ\x00\x01binary", "text/plain"),
    ],
)
def test_document_rejects_unexpected_or_spoofed_format(upload_client, tenant, name, body, mime):
    result = upload_client.post(
        "/api/documents-upload/",
        {
            "file": SimpleUploadedFile(name, body, content_type=mime),
        },
        format="multipart",
    )
    assert result.status_code == 400
    assert not Document.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_document_upload_enforces_byte_limit(upload_client, tenant, settings):
    settings.DOCUMENT_MAX_UPLOAD_BYTES = 32
    result = upload_client.post(
        "/api/documents-upload/",
        {
            "file": SimpleUploadedFile("oversized.txt", b"x" * 64, content_type="text/plain"),
        },
        format="multipart",
    )
    assert result.status_code == 413
    assert not Document.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["widget_logo", "widget_avatar"])
def test_public_branding_rejects_active_content_disguised_as_image(upload_client, tenant, field):
    result = upload_client.patch(
        "/api/widget-settings/mine/",
        {
            field: SimpleUploadedFile(
                "fake.png", b"<html><script>alert(1)</script></html>", content_type="image/png"
            ),
        },
        format="multipart",
    )
    assert result.status_code == 400
    tenant.refresh_from_db()
    assert not getattr(tenant, field)
