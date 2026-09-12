"""Streaming encrypted application bundle. No ZIP paths are extracted directly."""

import hashlib
import hmac
import json
import os
import struct
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from cryptography.fernet import InvalidToken
from django.apps import apps
from django.conf import settings
from django.core import serializers
from django.core.management import CommandError
from django.db import connection, models, transaction
from django.db.migrations.recorder import MigrationRecorder

from accounts.backups import backup_cipher
from accounts.management.commands.backup_data import POMIJANE
from chatbot_project.wersja import WERSJA

CHUNK = 1024 * 1024
MAX_ENTRIES = 4096
MAX_MANIFEST = 2 * CHUNK
DEFAULT_LIMIT = 512 * CHUNK
FIELDS = {
    ("documents.document", "file"): "private_documents",
    ("accounts.tenant", "widget_logo"): "public",
    ("accounts.tenant", "widget_avatar"): "public",
}


def fail():
    raise CommandError("Nieprawidłowa, niekompletna lub uszkodzona pełna kopia.")


def safe_name(name):
    if not isinstance(name, str) or not name or len(name) > 1024:
        fail()
    path = PurePosixPath(name)
    if (
        not path.parts
        or path.is_absolute()
        or str(path) != name
        or any(part in (".", "..") for part in path.parts)
        or any(c in name for c in '\\:\x00<>|?*"')
        or any(ord(c) < 32 for c in name)
        or any(part.endswith((".", " ")) for part in path.parts)
        or any(
            part.split(".")[0].upper()
            in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *[f"COM{i}" for i in range(10)],
                *[f"LPT{i}" for i in range(10)],
            }
            for part in path.parts
        )
    ):
        fail()
    return name


def backup_models():
    groups = []
    for app in apps.get_app_configs():
        selected = [
            model
            for model in app.get_models()
            if not model._meta.proxy
            and model._meta.managed
            and model._meta.app_label not in POMIJANE
            and model._meta.label_lower not in POMIJANE
        ]
        groups.append((app, selected))
    return serializers.sort_dependencies(groups, allow_cycles=True)


def stream_objects(counts):
    for model in backup_models():
        iterator = model._base_manager.order_by(model._meta.pk.name).iterator(chunk_size=1)
        try:
            for obj in iterator:
                counts[model._meta.label_lower] = counts.get(model._meta.label_lower, 0) + 1
                yield obj
        finally:
            iterator.close()


class BundleWriter:
    def __init__(self, archive, cipher, limit):
        self.archive, self.cipher, self.limit = archive, cipher, limit
        self.total = 0
        self.index = 0

    def block(self, data):
        self.total += len(data)
        self.index += 1
        if self.total > self.limit or self.index >= MAX_ENTRIES:
            raise CommandError("Pełna kopia przekracza limit rozmiaru lub liczby części.")
        name = f"data/{self.index:08d}"
        encrypted = self.cipher.encrypt(data)
        self.archive.writestr(name, encrypted)
        return {"entry": name, "sha256": hashlib.sha256(encrypted).hexdigest(), "size": len(data)}

    def binary(self, stream):
        parts = []
        digest = hashlib.sha256()
        size = 0
        while data := stream.read(CHUNK):
            if len(data) > CHUNK:
                fail()
            parts.append(self.block(data))
            digest.update(data)
            size += len(data)
        return {"parts": parts, "size": size, "sha256": digest.hexdigest()}


class DumpWriter:
    """Django dumpdata text sink, holding at most one encryption block."""

    def __init__(self, writer):
        self.writer = writer
        self.buffer = bytearray()
        self.digest = hashlib.sha256()
        self.parts = []
        self.size = 0

    def write(self, text):
        data = text.encode("utf-8")
        self.size += len(data)
        if self.size > settings.BACKUP_MAX_BYTES:
            raise CommandError("Zrzut bazy przekracza BACKUP_MAX_BYTES.")
        self.digest.update(data)
        for start in range(0, len(data), CHUNK):
            self.buffer.extend(data[start : start + CHUNK])
            while len(self.buffer) >= CHUNK:
                self.parts.append(self.writer.block(bytes(self.buffer[:CHUNK])))
                del self.buffer[:CHUNK]
        return len(text)

    def finish(self):
        if self.buffer:
            self.parts.append(self.writer.block(bytes(self.buffer)))
            self.buffer.clear()
        return {"parts": self.parts, "size": self.size, "sha256": self.digest.hexdigest()}


def references():
    result = {}
    count = 0
    for model in apps.get_models():
        for field in model._meta.fields:
            if not isinstance(field, models.FileField):
                continue
            alias = FIELDS.get((model._meta.label_lower, field.name))
            if alias is None:
                raise CommandError(
                    "Nowe pole pliku wymaga jawnego dodania do zakresu pełnej kopii."
                )
            values = (
                model._base_manager.exclude(**{field.name: ""})
                .exclude(**{field.name: None})
                .values_list("pk", field.name)[:MAX_ENTRIES]
            )
            for pk, name in values:
                if not name:
                    continue
                count += 1
                if count > MAX_ENTRIES - 2:
                    raise CommandError("Zbyt wiele odwołań do plików w pełnej kopii.")
                safe_name(name)
                key = (alias, name)
                if key not in result:
                    result[key] = {
                        "storage": alias,
                        "name": name,
                        "refs": [],
                        "reader": field.storage,
                    }
                result[key]["refs"].append(
                    {"model": model._meta.label_lower, "field": field.name, "pk": str(pk)}
                )
    return result


def create_bundle(stream, *, source_quiesced, limit=DEFAULT_LIMIT):
    if not source_quiesced:
        raise CommandError(
            "Wstrzymaj zapisy web/workera i potwierdź --source-quiesced przed kopią plików."
        )
    if connection.vendor != "postgresql" or connection.in_atomic_block:
        raise CommandError("Pełna kopia wymaga osobnej transakcji PostgreSQL.")
    cipher = backup_cipher()
    manifest = {"format": "saas-full-1", "id": uuid.uuid4().hex, "version": WERSJA, "files": []}
    manifest["django_key_proof"] = hmac.new(
        settings.SECRET_KEY.encode(), manifest["id"].encode(), hashlib.sha256
    ).hexdigest()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        writer = BundleWriter(archive, cipher, limit)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                cursor.execute("SELECT current_setting('server_version'), transaction_timestamp()")
                version, started = cursor.fetchone()
            manifest.update(postgres=version, snapshot_at=started.isoformat())
            manifest["migrations"] = sorted(
                [list(x) for x in MigrationRecorder(connection).applied_migrations()]
            )
            refs = references()
            output = DumpWriter(writer)
            manifest["model_counts"] = {}
            objects = stream_objects(manifest["model_counts"])
            try:
                serializers.serialize("json", objects, use_natural_foreign_keys=True, stream=output)
            finally:
                objects.close()
            manifest["database"] = output.finish()
            for item in refs.values():
                reader = item.pop("reader")
                try:
                    with reader.open(item["name"], "rb") as source:
                        item.update(writer.binary(source))
                except CommandError:
                    raise
                except Exception:
                    raise CommandError(
                        "Nie można odczytać pliku wskazanego przez bazę; kopia przerwana."
                    ) from None
                manifest["files"].append(item)
        manifest["total_bytes"] = writer.total
        payload = json.dumps(manifest, ensure_ascii=True, separators=(",", ":")).encode()
        if len(payload) > MAX_MANIFEST:
            raise CommandError("Manifest przekracza limit rozmiaru.")
        archive.writestr("manifest.fernet", cipher.encrypt(payload))
    return manifest


def manifest_from(archive, cipher, limit):
    infos = archive.infolist()
    if len(infos) > MAX_ENTRIES or len({i.filename for i in infos}) != len(infos):
        fail()
    if any(
        i.compress_type != zipfile.ZIP_STORED
        or i.flag_bits & 1
        or i.compress_size != i.file_size
        or i.file_size > 2 * MAX_MANIFEST
        for i in infos
    ):
        fail()
    info = archive.getinfo("manifest.fernet")
    if info.file_size > 2 * MAX_MANIFEST:
        fail()
    raw = cipher.decrypt(archive.read(info))
    if len(raw) > MAX_MANIFEST:
        fail()
    manifest = json.loads(raw)
    if manifest["format"] != "saas-full-1" or not 0 < manifest["total_bytes"] <= limit:
        fail()
    datetime.fromisoformat(manifest["snapshot_at"])
    paths = set()
    for item in manifest["files"]:
        if item["storage"] not in ("private_documents", "public"):
            fail()
        name = safe_name(item["name"])
        key = (item["storage"], name.casefold())
        if key in paths or not item["refs"]:
            fail()
        paths.add(key)
        for ref in item["refs"]:
            if FIELDS.get((ref["model"], ref["field"])) != item["storage"]:
                fail()
    for alias, name in paths:
        if any((alias, str(parent)) in paths for parent in PurePosixPath(name).parents):
            fail()
    return manifest


def read_item(archive, cipher, item, expected, sink=None):
    digest = hashlib.sha256()
    size = 0
    for part in item["parts"]:
        name = part["entry"]
        if name in expected or not name.startswith("data/"):
            fail()
        expected.add(name)
        info = archive.getinfo(name)
        if info.file_size > 2 * CHUNK or not 0 < part["size"] <= CHUNK:
            fail()
        encrypted = archive.read(info)
        if hashlib.sha256(encrypted).hexdigest() != part["sha256"]:
            fail()
        data = cipher.decrypt(encrypted)
        if len(data) != part["size"]:
            fail()
        size += len(data)
        digest.update(data)
        if sink:
            sink.write(data)
    if size != item["size"] or digest.hexdigest() != item["sha256"]:
        fail()
    return size


def verify_bundle(stream, *, limit=DEFAULT_LIMIT, max_age_hours=None):
    cipher = backup_cipher()
    try:
        # Bound the central directory BEFORE ZipFile allocates its entries.
        stream.seek(0, os.SEEK_END)
        length = stream.tell()
        if not 22 <= length <= 2 * limit + 4 * MAX_MANIFEST:
            fail()
        stream.seek(-22, os.SEEK_END)
        signature, disk, start_disk, local_count, count, directory_size, offset, comment = (
            struct.unpack("<4s4H2LH", stream.read(22))
        )
        if (
            signature != b"PK\x05\x06"
            or disk
            or start_disk
            or comment
            or count != local_count
            or count > MAX_ENTRIES
            or directory_size > CHUNK
            or offset + directory_size != length - 22
        ):
            fail()
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            manifest = manifest_from(archive, cipher, limit)
            expected = {"manifest.fernet"}
            size = 0
            for item in [manifest["database"], *manifest["files"]]:
                size += read_item(archive, cipher, item, expected)
                if size > limit:
                    fail()
            if size != manifest["total_bytes"] or expected != set(archive.namelist()):
                fail()
            age = (
                datetime.now(UTC) - datetime.fromisoformat(manifest["snapshot_at"])
            ).total_seconds()
            if age < -60 or (max_age_hours is not None and age > max_age_hours * 3600):
                raise CommandError("Pełna kopia ma nieprawidłowy lub przekroczony wiek.")
            return manifest
    except CommandError:
        raise
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        InvalidToken,
        zipfile.BadZipFile,
        RuntimeError,
        struct.error,
        AttributeError,
        OverflowError,
    ):
        fail()


def unpack_bundle(stream, directory):
    manifest = verify_bundle(stream)
    root = Path(directory).resolve()
    if root.is_relative_to(Path(settings.MEDIA_ROOT).resolve()):
        raise CommandError("Odtworzenie wymaga katalogu poza publicznym MEDIA_ROOT.")
    try:
        root.mkdir(mode=0o700, parents=False, exist_ok=False)
    except FileExistsError:
        raise CommandError(
            "Katalog docelowy musi być nowy; nie nadpisujemy istniejących danych."
        ) from None
    cipher = backup_cipher()
    stream.seek(0)
    with zipfile.ZipFile(stream) as archive:
        expected = {"manifest.fernet"}
        items = [(root / "database.json", manifest["database"])]
        items += [(root / item["storage"] / item["name"], item) for item in manifest["files"]]
        for target, item in items:
            if not target.resolve().is_relative_to(root):
                fail()
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(
                target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600
            )
            with os.fdopen(descriptor, "wb") as output:
                read_item(archive, cipher, item, expected, output)
        descriptor = os.open(
            root / "restore-manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(manifest, output, ensure_ascii=True)
    return manifest
