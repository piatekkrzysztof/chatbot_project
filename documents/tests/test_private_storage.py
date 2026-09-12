"""Granice między publicznym brandingiem a plikami firmy."""

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import CustomUser, Tenant
from api.session_tokens import SessionRefreshToken
from documents.models import Document


@pytest.fixture(autouse=True)
def private_test_directory(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private"


@pytest.fixture
def downloads(tenant, subscribtion):
    other = Tenant.objects.create(name="Inna firma")
    file = Document.objects.create(
        tenant=tenant, name="tajne.txt", file=SimpleUploadedFile("tajne.txt", b"PRIVATE_CONTENT")
    )
    foreign = Document.objects.create(
        tenant=other, name="Inny", file=SimpleUploadedFile("inny.txt", b"OTHER_SECRET")
    )
    users = {
        role: CustomUser.objects.create_user(username=role, tenant=tenant, role=role)
        for role in ("owner", "employee", "viewer")
    }
    return file, foreign, users


@pytest.mark.django_db
def test_nowy_dokument_nie_trafia_do_publicznych_mediow(tenant, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "public"
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private"
    document = Document.objects.create(
        tenant=tenant, name="Poufne", file=SimpleUploadedFile("tajne.txt", b"PRIVATE_CONTENT")
    )
    assert not (settings.MEDIA_ROOT / document.file.name).exists()
    with document.file.open("rb") as stream:
        assert stream.read() == b"PRIVATE_CONTENT"


@pytest.mark.django_db
def test_klucz_nowego_pliku_jest_powiazany_z_firma(tenant):
    document = Document.objects.create(
        tenant=tenant, name="Poufne", file=SimpleUploadedFile("tajne.txt", b"PRIVATE_CONTENT")
    )
    assert document.file.name.startswith(f"private-documents/{tenant.pk}/")
    assert "tajne" not in document.file.name


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["owner", "employee", "viewer"])
def test_pobieranie_wlasnego_pliku_wymaga_tozsamosci(downloads, role):
    document, _, users = downloads
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {SessionRefreshToken.for_user(users[role]).access_token}"
    )
    response = client.get(reverse("documents-download", args=[document.pk]))
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"PRIVATE_CONTENT"
    assert response["Cache-Control"] == "private, no-store"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Disposition"].startswith("attachment;")
    assert response["Content-Type"] == "application/octet-stream"
    response.close()


@pytest.mark.django_db
def test_cudza_firma_nie_otwiera_pliku(downloads, monkeypatch):
    _, foreign, users = downloads
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {SessionRefreshToken.for_user(users['owner']).access_token}"
    )
    from documents.storage import DocumentStorage

    opened = []
    monkeypatch.setattr(DocumentStorage, "_open", lambda *args: opened.append(args))
    response = client.get(reverse("documents-download", args=[foreign.pk]))
    assert response.status_code == 404
    assert opened == []


@pytest.mark.django_db
@pytest.mark.parametrize("credential", ["none", "widget", "expired", "conflicting"])
def test_publiczny_klucz_i_sprzeczne_dane_nie_pobieraja(downloads, credential):
    document, foreign, users = downloads
    client = APIClient()
    headers = {}
    if credential == "widget":
        headers["HTTP_X_API_KEY"] = str(document.tenant.api_key)
    elif credential == "expired":
        headers = {
            "HTTP_AUTHORIZATION": "Bearer invalid",
            "HTTP_X_API_KEY": str(document.tenant.api_key),
        }
    elif credential == "conflicting":
        headers = {
            "HTTP_AUTHORIZATION": (
                f"Bearer {SessionRefreshToken.for_user(users['owner']).access_token}"
            ),
            "HTTP_X_API_KEY": str(foreign.tenant.api_key),
        }
    client.credentials(**headers)
    response = client.get(reverse("documents-download", args=[document.pk]))
    assert response.status_code == (403 if credential == "conflicting" else 401)


@pytest.mark.django_db
def test_legacy_odczyt_i_przelaczenie_bez_zmiany_rekordu(tenant, settings):
    name = storages["default"].save("documents/legacy.txt", ContentFile(b"OLD"))
    document = Document.objects.create(tenant=tenant, name="Legacy", file=name)
    with document.file.open("rb") as stream:
        assert stream.read() == b"OLD"
    storages["private_documents"].save(name, ContentFile(b"PRIVATE_COPY"))
    settings.ALLOW_LEGACY_DOCUMENT_READS = False
    document.refresh_from_db()
    with document.file.open("rb") as stream:
        assert stream.read() == b"PRIVATE_COPY"
    document.refresh_from_db()
    assert document.file.name == name


@pytest.mark.django_db
def test_wylaczenie_legacy_nie_wraca_do_publicznego_pliku(tenant, settings):
    name = storages["default"].save("documents/legacy.txt", ContentFile(b"OLD"))
    document = Document.objects.create(tenant=tenant, name="Legacy", file=name)
    settings.ALLOW_LEGACY_DOCUMENT_READS = False
    with pytest.raises(FileNotFoundError):
        document.file.open("rb")


@pytest.mark.django_db
def test_dokument_nie_udostepnia_publicznego_url(downloads):
    document, _, _ = downloads
    with pytest.raises(ValueError, match="API"):
        _ = document.file.url


@pytest.mark.django_db
def test_blad_prywatnego_magazynu_nie_powoduje_publicznego_fallbacku(tenant, monkeypatch):
    name = storages["default"].save("documents/legacy.txt", ContentFile(b"OLD"))
    document = Document.objects.create(tenant=tenant, name="Legacy", file=name)

    def denied(*args):
        raise PermissionError("Private storage denied")

    monkeypatch.setattr(storages["private_documents"], "exists", denied)
    with pytest.raises(PermissionError):
        document.file.open("rb")


@pytest.mark.django_db
def test_brak_pliku_zwraca_404(downloads):
    document, _, users = downloads
    storages["private_documents"].delete(document.file.name)
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {SessionRefreshToken.for_user(users['owner']).access_token}"
    )
    response = client.get(reverse("documents-download", args=[document.pk]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_publiczny_branding_nadal_uzywa_domyslnego_magazynu(tenant):
    tenant.widget_logo = SimpleUploadedFile("logo.svg", b"PUBLIC_LOGO")
    tenant.save()
    assert storages["default"].exists(tenant.widget_logo.name)
    assert not storages["private_documents"].exists(tenant.widget_logo.name)


@pytest.mark.django_db
def test_brak_private_storage_odmawia_uploadu_przed_zapisem(downloads, settings):
    document, _, users = downloads
    settings.STORAGES = {
        **settings.STORAGES,
        "private_documents": {"BACKEND": "chatbot_project.storage.UnconfiguredPrivateStorage"},
    }
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {SessionRefreshToken.for_user(users['owner']).access_token}"
    )
    before = Document.objects.count()
    response = client.post(
        reverse("upload-document"),
        {"file": SimpleUploadedFile("test.txt", b"SECRET")},
        format="multipart",
    )
    assert response.status_code == 503
    assert Document.objects.count() == before
    assert not storages["default"].exists(f"documents/{document.file.name}")
