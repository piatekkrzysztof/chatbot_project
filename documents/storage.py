"""Nowy zapis zawsze prywatny; zgodny odczyt podczas migracji istniejących plików."""

import uuid
from pathlib import PurePosixPath

from django.conf import settings
from django.core.files.storage import Storage, storages
from django.utils.deconstruct import deconstructible

from chatbot_project.storage import UnconfiguredPrivateStorage


def private_document_name(instance, filename):
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    return f"private-documents/{instance.tenant_id}/{uuid.uuid4().hex}{suffix}"


@deconstructible
class DocumentStorage(Storage):
    @property
    def private(self):
        return storages["private_documents"]

    def _reader(self, name):
        if name.startswith("private-documents/"):
            return self.private
        if not isinstance(self.private, UnconfiguredPrivateStorage) and self.private.exists(name):
            return self.private
        if settings.ALLOW_LEGACY_DOCUMENT_READS:
            return storages["default"]
        raise FileNotFoundError("Dokument nie został przeniesiony do prywatnego magazynu.")

    def _open(self, name, mode="rb"):
        if mode not in ("r", "rb"):
            raise ValueError("Uchwyt dokumentu służy wyłącznie do odczytu.")
        return self._reader(name).open(name, mode)

    def _save(self, name, content):
        return self.private.save(name, content)

    def exists(self, name):
        try:
            return self._reader(name).exists(name)
        except FileNotFoundError:
            return False

    def size(self, name):
        return self._reader(name).size(name)

    def delete(self, name):
        return self._reader(name).delete(name)

    def url(self, name):
        raise ValueError("Dokumenty pobiera się przez API po sprawdzeniu firmy użytkownika.")
