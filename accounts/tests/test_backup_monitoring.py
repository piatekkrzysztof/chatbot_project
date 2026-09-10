"""Awaria zapisu, brak harmonogramu i stara kopia mają dawać głośny błąd."""

import io
import json
import time
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from django.core.files.base import ContentFile
from django.core.management import CommandError, call_command

from accounts.backups import MAGIC, backup_cipher, decrypt_backup
from chatbot_project.storage import PrivateS3Storage

PAYLOAD = b'[{"model":"accounts.tenant","pk":1,"fields":{"name":"PRIVATE_SENTINEL"}}]'


@pytest.fixture
def remote_backups(settings, monkeypatch):
    settings.STORAGES = {
        **settings.STORAGES,
        "private_backups": {
            "BACKEND": "chatbot_project.storage.PrivateS3Storage",
            "OPTIONS": {"bucket_name": "synthetic", "access_key": "test", "secret_key": "test"},
        },
    }
    objects = {}

    def save(self, name, content, max_length=None):
        objects[name] = content.read()
        return name

    def open_file(self, name, mode="rb"):
        return ContentFile(objects[name])

    monkeypatch.setattr(PrivateS3Storage, "save", save)
    monkeypatch.setattr(PrivateS3Storage, "open", open_file)
    monkeypatch.setattr(
        PrivateS3Storage, "listdir", lambda self, path: ([], [k.split("/", 1)[1] for k in objects])
    )
    return objects


@pytest.fixture
def synthetic_dump(monkeypatch):
    monkeypatch.setattr(
        "accounts.management.commands.backup_data.call_command",
        lambda *a, **kw: kw["stdout"].write(PAYLOAD.decode()),
    )


def add_backup(objects, *, age=0, contents=PAYLOAD, timestamp=None, filename_age=None):
    timestamp = int(time.time()) - age if timestamp is None else timestamp
    named_at = timestamp if filename_age is None else int(time.time()) - filename_age
    date = datetime.fromtimestamp(named_at, UTC).strftime("%Y%m%d-%H%M%S")
    name = f"backups/kopia-{date}-{'a' * 32}.json.fernet"
    objects[name] = MAGIC + backup_cipher().encrypt_at_time(contents, timestamp)
    return name


def test_remote_write_is_read_back_before_success(remote_backups, synthetic_dump, monkeypatch):
    monkeypatch.setattr(PrivateS3Storage, "open", lambda *a, **k: ContentFile(b"CORRUPTED"))
    output = io.StringIO()
    with pytest.raises(CommandError, match="weryfikac"):
        call_command("backup_data", to_storage=True, stdout=output)
    assert "Wysłano" not in output.getvalue()


def test_remote_success_and_monitor_do_not_write_plaintext(
    remote_backups, synthetic_dump, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    call_command("backup_data", to_storage=True)
    output = io.StringIO()
    call_command("check_backup", stdout=output)
    result = json.loads(output.getvalue())
    assert result["status"] == "ok"
    assert result["objects"] == 1
    assert result["age_seconds"] < 60
    assert "PRIVATE_SENTINEL" not in output.getvalue()
    assert not list(tmp_path.iterdir())
    assert len(remote_backups) == 1
    assert decrypt_backup(next(iter(remote_backups.values()))) == PAYLOAD


def test_monitor_requires_remote_private_storage():
    with pytest.raises(CommandError, match="prywatnego magazynu"):
        call_command("check_backup")


def test_no_backup_is_an_error(remote_backups):
    with pytest.raises(CommandError, match="Brak"):
        call_command("check_backup")


@pytest.mark.parametrize("age", [30 * 3600 + 1, 48 * 3600])
def test_stale_backup_is_an_error(remote_backups, age):
    add_backup(remote_backups, age=age)
    with pytest.raises(CommandError, match="starsza"):
        call_command("check_backup")


def test_renaming_old_ciphertext_does_not_refresh_backup(remote_backups):
    add_backup(remote_backups, age=48 * 3600, filename_age=0)
    with pytest.raises(CommandError, match="starsza"):
        call_command("check_backup")


def test_future_ciphertext_is_an_error(remote_backups):
    add_backup(remote_backups, age=-3600)
    with pytest.raises(CommandError, match="przysz"):
        call_command("check_backup")


@pytest.mark.parametrize("payload", [b"[]", b"not JSON", b'{"wrong":"shape"}'])
def test_valid_encryption_does_not_hide_invalid_dump(remote_backups, payload):
    add_backup(remote_backups, contents=payload)
    with pytest.raises(CommandError):
        call_command("check_backup")


def test_corrupted_newest_copy_does_not_fall_back_to_older_one(remote_backups):
    add_backup(remote_backups, age=3600)
    newest = add_backup(remote_backups)
    remote_backups[newest] = b"CORRUPTED"
    with pytest.raises(CommandError):
        call_command("check_backup")


def test_wrong_key_is_an_error(remote_backups, settings):
    add_backup(remote_backups)
    settings.BACKUP_ENCRYPTION_KEY = Fernet.generate_key().decode()
    with pytest.raises(CommandError, match="błędny klucz"):
        call_command("check_backup")


@pytest.mark.parametrize("limit", ["0", "-1", "nan", "inf"])
def test_invalid_age_threshold_is_rejected(remote_backups, limit):
    add_backup(remote_backups)
    with pytest.raises(CommandError):
        call_command("check_backup", max_age_hours=float(limit))


def test_custom_age_threshold_is_used(remote_backups):
    add_backup(remote_backups, age=2 * 3600)
    with pytest.raises(CommandError, match="starsza"):
        call_command("check_backup", max_age_hours=1)
    call_command("check_backup", max_age_hours=3)


@pytest.mark.parametrize("operation", ["listdir", "open"])
def test_storage_errors_do_not_leak_details(remote_backups, monkeypatch, operation):
    add_backup(remote_backups)

    def fail(*args, **kwargs):
        raise OSError("SECRET_SENTINEL https://signed.example.test/?credential=secret")

    monkeypatch.setattr(PrivateS3Storage, operation, fail)
    with pytest.raises(CommandError) as raised:
        call_command("check_backup")
    assert "SECRET_SENTINEL" not in str(raised.value)
    assert "signed.example" not in str(raised.value)


def test_oversized_remote_copy_is_rejected(remote_backups, settings):
    name = add_backup(remote_backups)
    settings.BACKUP_MAX_BYTES = 20
    remote_backups[name] = b"X" * 3000
    with pytest.raises(CommandError, match="limit"):
        call_command("check_backup")


def test_unknown_files_are_not_accepted_as_scheduled_backups(remote_backups):
    remote_backups["backups/readme.txt"] = b"hello"
    with pytest.raises(CommandError, match="Brak"):
        call_command("check_backup")


@pytest.mark.parametrize("operation", ["save", "open"])
def test_backup_io_failure_never_reports_remote_success(
    remote_backups, synthetic_dump, monkeypatch, operation
):
    def fail(*args, **kwargs):
        raise OSError("SECRET_SENTINEL")

    monkeypatch.setattr(PrivateS3Storage, operation, fail)
    output = io.StringIO()
    with pytest.raises(CommandError) as raised:
        call_command("backup_data", to_storage=True, stdout=output)
    assert "SECRET_SENTINEL" not in str(raised.value)
    assert "Wysłano" not in output.getvalue()


def test_modified_ciphertext_is_rejected(remote_backups):
    name = add_backup(remote_backups)
    value = bytearray(remote_backups[name])
    value[-10] = ord("a") if value[-10] != ord("a") else ord("b")
    remote_backups[name] = bytes(value)
    with pytest.raises(CommandError, match="uszkodzone"):
        call_command("check_backup")


def test_backup_does_not_import_http_routes(remote_backups, synthetic_dump, settings):
    settings.ROOT_URLCONF = "nonexistent_http_routes_on_backup_host"
    call_command("backup_data", to_storage=True, skip_checks=False)


@pytest.mark.parametrize("age,allowed", [(3600, True), (3601, False), (-60, True), (-61, False)])
def test_age_boundaries(remote_backups, monkeypatch, age, allowed):
    now = 1789041600
    monkeypatch.setattr("accounts.backups.time.time", lambda: now)
    add_backup(remote_backups, age=age)
    if allowed:
        call_command("check_backup", max_age_hours=1)
    else:
        with pytest.raises(CommandError):
            call_command("check_backup", max_age_hours=1)
