"""Format kopii, szyfrowanie i zapis bez nadpisywania poprzedniej kopii."""

import io
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.management.base import CommandError

MAGIC = b"SAAS-BACKUP-1\n"


def backup_cipher():
    key = settings.BACKUP_ENCRYPTION_KEY
    if not key:
        raise CommandError("Ustaw osobny BACKUP_ENCRYPTION_KEY przed wykonaniem kopii.")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeError) as error:
        raise CommandError("Niepoprawny BACKUP_ENCRYPTION_KEY; wymagany klucz Fernet.") from error


class BackupBuffer(io.StringIO):
    def __init__(self):
        super().__init__()
        self.byte_count = 0

    def write(self, value):
        self.byte_count += len(value.encode("utf-8"))
        if self.byte_count > settings.BACKUP_MAX_BYTES:
            raise CommandError(
                "Kopia przekracza limit pamięci; użyj kopii PostgreSQL dla dużej bazy."
            )
        return super().write(value)


def validate_backup(data):
    if len(data) > settings.BACKUP_MAX_BYTES:
        raise CommandError("Kopia przekracza limit pamięci.")
    try:
        objects = json.loads(data)
    except (ValueError, UnicodeError) as error:
        raise CommandError("Zrzut nie jest poprawnym JSON-em.") from error
    if not isinstance(objects, list) or not objects:
        raise CommandError("Zrzut jest pusty lub nie jest listą obiektów — przerywam.")
    return len(objects)


def encrypt_backup(data):
    validate_backup(data)
    return MAGIC + backup_cipher().encrypt(data)


def decrypt_backup(data):
    if not data.startswith(MAGIC):
        raise CommandError("Nieznany format kopii; oczekiwano zaszyfrowanej kopii SAAS-BACKUP-1.")
    try:
        plaintext = backup_cipher().decrypt(data[len(MAGIC) :])
    except InvalidToken as error:
        raise CommandError(
            "Nie można odszyfrować kopii: błędny klucz lub uszkodzone dane."
        ) from error
    validate_backup(plaintext)
    return plaintext


def read_backup(stream, *, encrypted=False):
    limit = settings.BACKUP_MAX_BYTES
    if encrypted:
        limit = (limit + 1024) * 2
    data = stream.read(limit + 1)
    if len(data) > limit:
        raise CommandError("Kopia przekracza limit pamięci.")
    return data


def write_new_file(path, data):
    path = Path(path).resolve()
    if path.is_relative_to(Path(settings.MEDIA_ROOT).resolve()):
        raise CommandError("Kopii nie wolno zapisywać w publicznym MEDIA_ROOT.")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600
        )
    except FileExistsError as error:
        raise CommandError(
            "Plik docelowy istnieje — wybierz nową nazwę; kopie nie są nadpisywane."
        ) from error
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
