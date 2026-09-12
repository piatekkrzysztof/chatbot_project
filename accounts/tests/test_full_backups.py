import hashlib
import io
import json
import os
import socket
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth.models import Group, Permission
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management import CommandError, call_command
from django.db import close_old_connections, connections, transaction
from django.utils import timezone

from accounts import totp
from accounts.backups import backup_cipher
from accounts.full_backups import CHUNK, create_bundle, unpack_bundle, verify_bundle
from accounts.models import CustomUser, DrugiSkladnik, Tenant
from accounts.security_notifications import PasswordNotification
from accounts.tests.test_backup_monitoring import remote_backups
from api.tests.factories import UserFactory
from documents.models import Document, DocumentChunk
from documents.wymiar import WYMIAR_WEKTORA

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def seed(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "public")
    settings.STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": settings.MEDIA_ROOT},
        },
        "private_documents": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(tmp_path / "private")},
        },
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    user = UserFactory()
    doc = Document.objects.create(
        tenant=user.tenant, name="Private-price-list", content="PRIVATE_DATABASE_SENTINEL"
    )
    doc.file.save("source.txt", ContentFile(b"PRIVATE_FILE_SENTINEL"))
    user.tenant.widget_logo.save("logo.png", ContentFile(b"PUBLIC_BRAND_SENTINEL"))
    user.tenant.widget_avatar = user.tenant.widget_logo.name
    user.tenant.save(update_fields=["widget_avatar"])
    return user, doc


def bundle():
    stream = io.BytesIO()
    manifest = create_bundle(stream, source_quiesced=True)
    stream.seek(0)
    return stream, manifest


def rewrite(stream, mutate):
    with zipfile.ZipFile(stream) as source:
        entries = {name: source.read(name) for name in source.namelist()}
    mutate(entries)
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_STORED) as target:
        for name, value in entries.items():
            target.writestr(name, value)
    result.seek(0)
    return result


def change_manifest(entries, callback):
    cipher = backup_cipher()
    data = json.loads(cipher.decrypt(entries["manifest.fernet"]))
    callback(data)
    entries["manifest.fernet"] = cipher.encrypt(json.dumps(data).encode())


def test_full_roundtrip_restores_bytes_relations_password_mfa_vectors_and_permissions(
    seed, tmp_path, settings
):
    user, doc = seed
    second = UserFactory()
    other = Document.objects.create(
        tenant=second.tenant, name="Other company", content="OTHER_COMPANY"
    )
    other.file.save("other.txt", ContentFile(b"OTHER_FILE"))
    mfa = DrugiSkladnik.objects.create(
        uzytkownik=user, sekret=totp.nowy_sekret(), potwierdzony_od=timezone.now()
    )
    secret = mfa.sekret
    DocumentChunk.objects.create(
        document=doc, content="CHUNK_SENTINEL", embedding=[0.25] * WYMIAR_WEKTORA
    )
    permission = Permission.objects.get(
        codename="view_document", content_type__app_label="documents"
    )
    group = Group.objects.create(name="restored-test-group")
    group.permissions.add(permission)
    user.groups.add(group)
    PasswordNotification.objects.create(user=user, recipient=user.email)
    user_id, tenant_id, doc_id, other_id = user.pk, user.tenant_id, doc.pk, other.pk
    file_name, logo_name = doc.file.name, user.tenant.widget_logo.name
    raw, metadata = bundle()
    assert len(metadata["files"]) == 3
    assert all(
        value not in raw.getvalue()
        for value in [
            b"PRIVATE_FILE_SENTINEL",
            b"PRIVATE_DATABASE_SENTINEL",
            user.email.encode(),
            file_name.encode(),
        ]
    )
    assert verify_bundle(raw) == metadata
    Tenant.objects.all().delete()
    group.delete()
    for item in metadata["files"]:
        alias = "private_documents" if item["storage"] == "private_documents" else "default"
        storages[alias].delete(item["name"])
    destination = tmp_path / "isolated-restore"
    unpack_bundle(raw, destination)
    assert not Tenant.objects.exists()  # Unpacking never touches the connected DB.
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(destination / "public")},
        },
        "private_documents": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(destination / "private_documents")},
        },
    }
    with patch(
        "django.core.mail.EmailMessage.send",
        side_effect=AssertionError("Restore cannot send email"),
    ):
        call_command("loaddata", str(destination / "database.json"), verbosity=0)
    restored = CustomUser.objects.get(pk=user_id)
    assert restored.check_password("testpass123") and restored.tenant_id == tenant_id
    assert restored.has_perm("documents.view_document")
    assert DrugiSkladnik.objects.get(uzytkownik=restored).sekret == secret
    assert PasswordNotification.objects.get().status == "pending"
    restored_doc = Document.objects.get(pk=doc_id)
    assert (
        restored_doc.file.name == file_name and restored_doc.file.read() == b"PRIVATE_FILE_SENTINEL"
    )
    assert restored.tenant.widget_logo.read() == b"PUBLIC_BRAND_SENTINEL"
    assert restored.tenant.widget_avatar.name == logo_name
    assert Document.objects.get(pk=other_id).file.read() == b"OTHER_FILE"
    assert not Document.objects.filter(pk=other_id, tenant_id=tenant_id).exists()
    assert list(restored_doc.chunks.get().embedding) == [0.25] * WYMIAR_WEKTORA


def test_missing_file_fails_instead_of_publishing_partial_backup(seed, tmp_path):
    seed[1].file.storage.delete(seed[1].file.name)
    target = tmp_path / "backup.saas"
    with pytest.raises(CommandError, match="odczytać pliku"):
        call_command("backup_full", source_quiesced=True, output=str(target))
    assert not target.exists()


def test_explicit_quiescence_required_before_reading_data(seed, tmp_path):
    with patch("accounts.full_backups.references", side_effect=AssertionError):
        with pytest.raises(CommandError, match="wstrzymaj"):
            call_command("backup_full", output=str(tmp_path / "backup.saas"))


def test_consistent_snapshot_cannot_be_nested_in_existing_transaction(seed):
    with transaction.atomic(), pytest.raises(CommandError, match="osobnej transakcji"):
        create_bundle(io.BytesIO(), source_quiesced=True)


@pytest.mark.parametrize(
    "kind",
    ["corrupt", "missing", "extra", "wrong_order", "wrong_size", "wrong_hash", "bad_manifest"],
)
def test_corruption_and_incomplete_members_rejected_before_output(seed, tmp_path, kind):
    raw, _ = bundle()

    def mutate(entries):
        name = next(n for n in entries if n.startswith("data/"))
        if kind == "corrupt":
            entries[name] = b"X" + entries[name][1:]
        elif kind == "missing":
            del entries[name]
        elif kind == "extra":
            entries["extra"] = b"hello"
        elif kind == "bad_manifest":
            entries["manifest.fernet"] = b"bad"
        else:

            def corrupt(meta):
                if kind == "wrong_order":
                    meta["files"][0]["parts"] = meta["database"]["parts"]
                elif kind == "wrong_size":
                    meta["database"]["size"] += 1
                else:
                    meta["files"][0]["sha256"] = "0" * 64

            change_manifest(entries, corrupt)

    bad = rewrite(raw, mutate)
    destination = tmp_path / "must-not-exist"
    with pytest.raises(CommandError):
        unpack_bundle(bad, destination)
    assert not destination.exists()


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute", "a\\b", "C:drive", "a/../b", "a//b", "NUL.txt", "a.", "."]
)
def test_manifest_cannot_escape_or_alias_destination(seed, tmp_path, name):
    raw, _ = bundle()
    bad = rewrite(
        raw,
        lambda entries: change_manifest(entries, lambda meta: meta["files"][0].update(name=name)),
    )
    with pytest.raises(CommandError):
        unpack_bundle(bad, tmp_path / "restore")
    assert not (tmp_path / "restore").exists()


def test_wrong_key_does_not_create_output(seed, tmp_path, settings):
    raw, _ = bundle()
    settings.BACKUP_ENCRYPTION_KEY = Fernet.generate_key().decode()
    with pytest.raises(CommandError):
        unpack_bundle(raw, tmp_path / "restore")
    assert not (tmp_path / "restore").exists()


def test_existing_output_and_public_media_are_refused(seed, tmp_path, settings):
    target = tmp_path / "original.saas"
    target.write_bytes(b"DO_NOT_REPLACE")
    with pytest.raises(FileExistsError):
        call_command("backup_full", source_quiesced=True, output=str(target))
    assert target.read_bytes() == b"DO_NOT_REPLACE"
    raw, _ = bundle()
    with pytest.raises(CommandError, match="nowy"):
        unpack_bundle(raw, tmp_path)
    with pytest.raises(CommandError, match="publicznym"):
        unpack_bundle(raw, tmp_path / "public" / "restore")


def test_chunked_large_file_and_empty_file_are_restorable(seed, tmp_path):
    user, doc = seed
    payload = b"x" * (2 * CHUNK + 17)
    doc.file.save("large.txt", ContentFile(payload))
    empty = Document.objects.create(tenant=user.tenant)
    empty.file.save("empty.txt", ContentFile(b""))
    raw, metadata = bundle()
    item = next(i for i in metadata["files"] if i["name"] == doc.file.name)
    assert len(item["parts"]) == 3
    unpack_bundle(raw, tmp_path / "restore")
    assert (tmp_path / "restore/private_documents" / doc.file.name).read_bytes() == payload
    assert (tmp_path / "restore/private_documents" / empty.file.name).read_bytes() == b""


def test_boundaries_refuse_oversize_plaintext_database_and_archive(seed, settings):
    with pytest.raises(CommandError, match="limit"):
        create_bundle(io.BytesIO(), source_quiesced=True, limit=1)
    raw, _ = bundle()
    with pytest.raises(CommandError):
        verify_bundle(raw, limit=1)
    settings.BACKUP_MAX_BYTES = 10
    with pytest.raises(CommandError, match="BACKUP_MAX_BYTES"):
        bundle()


def test_full_backup_age_uses_authenticated_snapshot_time(seed):
    raw, _ = bundle()
    old = rewrite(
        raw,
        lambda entries: change_manifest(
            entries,
            lambda meta: meta.update(snapshot_at=(timezone.now() - timedelta(days=3)).isoformat()),
        ),
    )
    with pytest.raises(CommandError, match="wiek"):
        verify_bundle(old, max_age_hours=30)


def test_compressed_or_duplicate_members_are_rejected(seed):
    raw, _ = bundle()
    with zipfile.ZipFile(raw) as source:
        entries = {n: source.read(n) for n in source.namelist()}
    for compression, duplicate in [(zipfile.ZIP_DEFLATED, False), (zipfile.ZIP_STORED, True)]:
        bad = io.BytesIO()
        with zipfile.ZipFile(bad, "w", compression=compression) as archive:
            for name, value in entries.items():
                archive.writestr(name, value)
            if duplicate:
                archive.writestr("manifest.fernet", entries["manifest.fernet"])
        with pytest.raises(CommandError):
            verify_bundle(bad)


def test_commands_report_no_plaintext_data(seed, tmp_path):
    archive = tmp_path / "full.saas"
    output = io.StringIO()
    call_command("backup_full", source_quiesced=True, output=str(archive), stdout=output)
    call_command("verify_full_backup", str(archive), stdout=output)
    call_command(
        "unpack_full_backup", str(archive), output=str(tmp_path / "restore"), stdout=output
    )
    assert "PRIVATE" not in output.getvalue() and seed[0].email not in output.getvalue()


def test_remote_full_backup_is_read_back_and_verified(seed, remote_backups):
    call_command("backup_full", source_quiesced=True, to_storage=True)
    assert len(remote_backups) == 1
    name = next(iter(remote_backups))
    assert name.startswith("full-backups/") and name.endswith(".saas")
    assert b"PRIVATE_FILE_SENTINEL" not in remote_backups[name]
    call_command("verify_full_backup", name, from_storage=True)


def test_corrupt_remote_readback_never_reports_success(seed, remote_backups, monkeypatch):
    from chatbot_project.storage import PrivateS3Storage

    monkeypatch.setattr(PrivateS3Storage, "open", lambda *args, **kwargs: ContentFile(b"CORRUPT"))
    out = io.StringIO()
    with pytest.raises(CommandError):
        call_command("backup_full", source_quiesced=True, to_storage=True, stdout=out)
    assert "zweryfikowano" not in out.getvalue()


def test_guarded_restore_command_works_on_empty_local_database(seed, tmp_path):
    user, doc = seed
    pk = user.pk
    archive = tmp_path / "full.saas"
    call_command("backup_full", source_quiesced=True, output=str(archive))
    Tenant.objects.all().delete()
    result = io.StringIO()
    call_command(
        "restore_full_backup", str(archive), output=str(tmp_path / "restored"), stdout=result
    )
    assert CustomUser.objects.get(pk=pk).check_password("testpass123")
    assert (
        tmp_path / "restored/private_documents" / doc.file.name
    ).read_bytes() == b"PRIVATE_FILE_SENTINEL"
    assert "odtworzenie zakończone" in result.getvalue()


@pytest.mark.parametrize(
    "reason",
    ["nonempty", "render", "django_key", "schema", "version", "postgres", "remote", "dbname"],
)
def test_restore_rejects_unsafe_or_incompatible_target(
    seed, tmp_path, settings, monkeypatch, reason
):
    from django.db import connection

    raw, _ = bundle()
    if reason != "nonempty":
        Tenant.objects.all().delete()
    if reason == "render":
        monkeypatch.setenv("RENDER", "true")
    elif reason == "django_key":
        settings.SECRET_KEY = "different-synthetic-restore-key"
    elif reason in ("schema", "version", "postgres"):
        key, value = {
            "schema": ("migrations", []),
            "version": ("version", "0.0.0"),
            "postgres": ("postgres", "1.0"),
        }[reason]
        raw = rewrite(
            raw, lambda entries: change_manifest(entries, lambda meta: meta.update({key: value}))
        )
    elif reason == "remote":
        monkeypatch.setitem(connection.settings_dict, "HOST", "production.example.test")
    elif reason == "dbname":
        monkeypatch.setitem(connection.settings_dict, "NAME", "production")
    archive = tmp_path / "test.saas"
    archive.write_bytes(raw.getvalue())
    destination = tmp_path / "must-not-exist"
    with pytest.raises(CommandError):
        call_command("restore_full_backup", str(archive), output=str(destination))
    assert not destination.exists()


def test_restore_rechecks_empty_database_after_unpack(seed, tmp_path):
    archive = tmp_path / "test.saas"
    call_command("backup_full", source_quiesced=True, output=str(archive))
    Tenant.objects.all().delete()

    def race(*args, **kwargs):
        result = unpack_bundle(*args, **kwargs)
        Tenant.objects.create(name="Concurrent writer", owner_email="test@example.test")
        return result

    with patch("accounts.management.commands.restore_full_backup.unpack_bundle", side_effect=race):
        with pytest.raises(CommandError, match="zawiera dane"):
            call_command("restore_full_backup", str(archive), output=str(tmp_path / "partial"))
    assert Tenant.objects.get().name == "Concurrent writer"


def test_restore_database_failure_rolls_back_all_imported_rows(seed, tmp_path):
    archive = tmp_path / "test.saas"
    call_command("backup_full", source_quiesced=True, output=str(archive))
    Tenant.objects.all().delete()

    def fail(*args, **kwargs):
        Tenant.objects.create(name="partial")
        raise CommandError("SENSITIVE fixture contents")

    with patch("accounts.management.commands.restore_full_backup.call_command", side_effect=fail):
        with pytest.raises(CommandError) as raised:
            call_command("restore_full_backup", str(archive), output=str(tmp_path / "partial"))
    assert "SENSITIVE" not in str(raised.value)
    assert not Tenant.objects.exists()


def test_restore_blocks_mail_network_and_dns(seed, tmp_path, settings):
    archive = tmp_path / "test.saas"
    call_command("backup_full", source_quiesced=True, output=str(archive))
    Tenant.objects.all().delete()

    def load(*args, **kwargs):
        assert settings.EMAIL_BACKEND.endswith("dummy.EmailBackend")
        assert not settings.CELERY_TASK_ALWAYS_EAGER
        assert settings.CELERY_BROKER_URL == "memory://"
        with socket.socket() as sock, pytest.raises(CommandError):
            sock.connect(("1.1.1.1", 443))
        with pytest.raises(CommandError):
            socket.getaddrinfo("external.example.test", 443)
        return call_command(*args, **kwargs)

    with patch("accounts.management.commands.restore_full_backup.call_command", side_effect=load):
        call_command("restore_full_backup", str(archive), output=str(tmp_path / "restored"))


def test_restore_checks_complete_file_set_not_only_present_references(seed, tmp_path):
    raw, _ = bundle()

    def remove(entries):
        def edit(meta):
            item = meta["files"].pop()
            meta["total_bytes"] -= item["size"]
            for part in item["parts"]:
                del entries[part["entry"]]

        change_manifest(entries, edit)

    incomplete = rewrite(raw, remove)
    archive = tmp_path / "incomplete.saas"
    archive.write_bytes(incomplete.getvalue())
    Tenant.objects.all().delete()
    with pytest.raises(CommandError, match="powiązania"):
        call_command("restore_full_backup", str(archive), output=str(tmp_path / "partial"))
    assert not Tenant.objects.exists()


def test_restore_checks_model_counts(seed, tmp_path):
    raw, _ = bundle()
    modified = rewrite(
        raw,
        lambda entries: change_manifest(
            entries, lambda meta: meta["model_counts"].update({"accounts.tenant": 999})
        ),
    )
    archive = tmp_path / "count.saas"
    archive.write_bytes(modified.getvalue())
    Tenant.objects.all().delete()
    with pytest.raises(CommandError, match="rekordów"):
        call_command("restore_full_backup", str(archive), output=str(tmp_path / "partial"))
    assert not Tenant.objects.exists()


def test_unknown_file_field_fails_closed(seed, monkeypatch):
    from accounts.full_backups import FIELDS

    monkeypatch.delitem(FIELDS, ("documents.document", "file"))
    with pytest.raises(CommandError, match="Nowe pole"):
        bundle()


def test_database_uses_one_snapshot_during_concurrent_update(seed, tmp_path):
    from accounts.full_backups import references

    doc = seed[1]

    def update():
        close_old_connections()
        try:
            Document.objects.filter(pk=doc.pk).update(content="NEW_VERSION")
        finally:
            connections.close_all()

    def refs():
        result = references()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(update).result(timeout=10)
        return result

    with patch("accounts.full_backups.references", side_effect=refs):
        raw, _ = bundle()
    unpack_bundle(raw, tmp_path / "restore")
    data = json.loads((tmp_path / "restore/database.json").read_text())
    restored = next(row for row in data if row["model"] == "documents.document")
    assert restored["fields"]["content"] == "PRIVATE_DATABASE_SENTINEL"
    doc.refresh_from_db()
    assert doc.content == "NEW_VERSION"
