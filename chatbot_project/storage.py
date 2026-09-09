"""Osobne magazyny dla publicznego brandingu, dokumentów i kopii."""

import os
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage, Storage
from storages.backends.s3 import S3Storage


class UnconfiguredPrivateStorage(Storage):
    def _open(self, name, mode="rb"):
        raise ImproperlyConfigured("Prywatny magazyn plików nie został skonfigurowany.")

    def _save(self, name, content):
        return self._open(name)

    def exists(self, name):
        return self._open(name)


class PrivateFileSystemStorage(FileSystemStorage):
    def __init__(self, subdir):
        self.subdir = subdir
        super().__init__(file_permissions_mode=0o600, directory_permissions_mode=0o700)

    @property
    def base_location(self):
        root = Path(settings.PRIVATE_MEDIA_ROOT).resolve()
        if root.is_relative_to(Path(settings.MEDIA_ROOT).resolve()):
            raise ImproperlyConfigured("PRIVATE_MEDIA_ROOT musi leżeć poza MEDIA_ROOT.")
        return str(root / self.subdir)

    @property
    def location(self):
        return self.base_location

    def url(self, name):
        raise ValueError("Prywatne pliki wymagają uwierzytelnionego endpointu pobierania.")


class PrivateS3Storage(S3Storage):
    def __init__(self, **kwargs):
        # Ustawienia publicznych logo nie mogą wyłączyć podpisu lub włączyć CDN.
        kwargs.update(
            custom_domain=None,
            querystring_auth=True,
            querystring_expire=60,
            default_acl=None,
            file_overwrite=False,
            location="",
            object_parameters={"CacheControl": "private, no-store"},
            signature_version="s3v4",
            use_ssl=True,
            verify=True,
            cloudfront_signer=None,
            cloudfront_key=None,
            cloudfront_key_id=None,
            session_profile=None,
            security_token=None,
        )
        super().__init__(**kwargs)


def private_storage_config(prefix, public_bucket, other_bucket=""):
    """Brak konfiguracji zamyka zapis; nie przełącza go na publiczny dysk/S3."""
    bucket = os.getenv(f"{prefix}_STORAGE_BUCKET_NAME", "").strip()
    access = os.getenv(f"{prefix}_ACCESS_KEY_ID", "").strip()
    secret = os.getenv(f"{prefix}_SECRET_ACCESS_KEY", "").strip()
    if not all((bucket, access, secret)):
        return {"BACKEND": "chatbot_project.storage.UnconfiguredPrivateStorage"}
    if bucket in (public_bucket, other_bucket):
        raise ImproperlyConfigured(f"{prefix}_STORAGE_BUCKET_NAME wymaga osobnego bucketa.")
    endpoint = os.getenv(f"{prefix}_S3_ENDPOINT_URL", "").strip() or None
    if endpoint and not endpoint.startswith("https://"):
        raise ImproperlyConfigured(f"{prefix}_S3_ENDPOINT_URL musi używać HTTPS.")
    return {
        "BACKEND": "chatbot_project.storage.PrivateS3Storage",
        "OPTIONS": {
            "bucket_name": bucket,
            "access_key": access,
            "secret_key": secret,
            "endpoint_url": endpoint,
            "region_name": os.getenv(f"{prefix}_S3_REGION_NAME", "auto"),
        },
    }
