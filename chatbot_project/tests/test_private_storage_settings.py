from urllib.parse import parse_qs, urlsplit

import pytest
from django.core.exceptions import ImproperlyConfigured

from chatbot_project.storage import (
    PrivateFileSystemStorage,
    PrivateS3Storage,
    private_storage_config,
)


def configure(monkeypatch, prefix="DOCUMENTS", bucket="private-documents"):
    for name, value in {
        "STORAGE_BUCKET_NAME": bucket,
        "ACCESS_KEY_ID": "synthetic-access",
        "SECRET_ACCESS_KEY": "synthetic-secret",
        "S3_ENDPOINT_URL": "https://storage.example.test",
    }.items():
        monkeypatch.setenv(f"{prefix}_{name}", value)


def test_brak_konfiguracji_nie_dziedziczy_publicznego_magazynu(monkeypatch):
    monkeypatch.delenv("DOCUMENTS_STORAGE_BUCKET_NAME", raising=False)
    assert private_storage_config("DOCUMENTS", "public")["BACKEND"].endswith(
        "UnconfiguredPrivateStorage"
    )


@pytest.mark.parametrize("bucket", ["public", "documents"])
def test_prywatne_magazyny_musza_byc_oddzielne(monkeypatch, bucket):
    configure(monkeypatch, "BACKUPS", bucket)
    with pytest.raises(ImproperlyConfigured, match="osobnego"):
        private_storage_config("BACKUPS", "public", "documents")


def test_prywatny_endpoint_wymaga_tls(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setenv("DOCUMENTS_S3_ENDPOINT_URL", "http://storage.example.test")
    with pytest.raises(ImproperlyConfigured, match="HTTPS"):
        private_storage_config("DOCUMENTS", "public")


def test_link_s3_jest_podpisany_i_nie_uzywa_publicznej_domeny(settings, monkeypatch):
    configure(monkeypatch)
    settings.AWS_QUERYSTRING_AUTH = False
    settings.AWS_S3_CUSTOM_DOMAIN = "public.example.test"
    settings.AWS_S3_OBJECT_PARAMETERS = {"ACL": "public-read"}
    storage = PrivateS3Storage(**private_storage_config("DOCUMENTS", "public")["OPTIONS"])
    url = urlsplit(storage.url("documents/private.txt"))
    query = parse_qs(url.query)
    assert url.scheme == "https" and url.hostname == "storage.example.test"
    assert query["X-Amz-Expires"] == ["60"]
    assert query["X-Amz-Signature"]
    assert storage.object_parameters == {"CacheControl": "private, no-store"}
    assert storage.default_acl is None
    assert storage.file_overwrite is False


def test_prywatny_dysk_nie_moze_byc_pod_publicznym_media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "public"
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "public" / "private"
    with pytest.raises(ImproperlyConfigured, match="poza MEDIA_ROOT"):
        _ = PrivateFileSystemStorage("documents").location


def test_check_deploy_wykrywa_brak_konfiguracji(settings):
    from documents.checks import private_storage_readiness

    settings.DEBUG = False
    settings.BACKUP_ENCRYPTION_KEY = ""
    settings.ALLOW_LEGACY_DOCUMENT_READS = True
    warnings = private_storage_readiness(None)
    assert {warning.id for warning in warnings} == {
        "documents.W002",
        "documents.W003",
        "documents.W004",
        "documents.W005",
    }
