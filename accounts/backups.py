"""Format kopii, szyfrowanie i zapis bez nadpisywania poprzedniej kopii."""

import hmac
import io
import json
import os
import re
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.files.storage import storages
from django.core.management.base import CommandError

from chatbot_project.storage import PrivateS3Storage

MAGIC = b"SAAS-BACKUP-1\n"
BACKUP_NAME = re.compile(r"kopia-[0-9]{8}-[0-9]{6}-[a-f0-9]{32}\.json\.fernet\Z")


def private_backup_storage():
    storage = storages["private_backups"]
    if not isinstance(storage, PrivateS3Storage):
        raise CommandError("Operacja wymaga skonfigurowanego prywatnego magazynu obiektowego.")
    return storage


def read_remote_backup(storage, name):
    try:
        with storage.open(name, "rb") as stream:
            return read_backup(stream, encrypted=True)
    except CommandError:
        raise
    except Exception:
        # Wyjątki dostawcy mogą zawierać podpisany URL lub identyfikatory kluczy.
        raise CommandError("Nie można odczytać kopii z prywatnego magazynu.") from None


def verify_remote_backup(storage, name, expected):
    actual = read_remote_backup(storage, name)
    if not hmac.compare_digest(actual, expected):
        raise CommandError("Błąd weryfikacji kopii: odczytane bajty różnią się od wysłanych.")


def latest_remote_backup(storage):
    try:
        _, names = storage.listdir("backups")
    except Exception:
        raise CommandError("Nie można odczytać listy kopii z prywatnego magazynu.") from None
    name = max((name for name in names if BACKUP_NAME.fullmatch(name)), default=None)
    if name is None:
        raise CommandError("Brak zaszyfrowanych kopii utworzonych przez backup_data.")
    return f"backups/{name}"


def check_backup_age(data, max_age_seconds):
    plaintext = decrypt_backup(data)
    # extract_timestamp weryfikuje podpis. Nazwa lub data uploadu starego pliku
    # nie mogą odmłodzić kopii. Nie ufamy LastModified z magazynu.
    created = backup_cipher().extract_timestamp(data[len(MAGIC) :])
    age = time.time() - created
    if age < -60:
        raise CommandError("Kopia ma datę z przyszłości; sprawdź zegary usług.")
    if age > max_age_seconds:
        raise CommandError("Najnowsza kopia jest starsza niż dopuszczalny próg.")
    return {
        "status": "ok",
        "created_at": created,
        "age_seconds": max(0, int(age)),
        "objects": validate_backup(plaintext),
    }


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
