import io

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management import CommandError, call_command

from accounts.backups import decrypt_backup
from documents.models import Document

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def storage_config(settings):
    settings.BACKUP_ENCRYPTION_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    settings.STORAGES = {
        name: {"BACKEND": "django.core.files.storage.InMemoryStorage"}
        for name in ("default", "private_documents", "private_backups")
    }


@pytest.fixture
def legacy(tenant):
    source = storages["default"]
    source.save("documents/old.txt", ContentFile(b"LEGACY_PRIVATE_CONTENT"))
    source.save(
        "backups/old.json",
        ContentFile(b'[{"model":"accounts.tenant","fields":{"name":"PRIVATE"}}]'),
    )
    source.save("widget_branding/logo.svg", ContentFile(b"PUBLIC_LOGO"))
    document = Document.objects.create(tenant=tenant, name="Legacy", file="documents/old.txt")
    return source, document


def run(**kwargs):
    call_command("migrate_private_files", stdout=io.StringIO(), **kwargs)


def test_dry_run_nic_nie_zapisuje_i_nie_kasuje(legacy):
    source, _ = legacy
    run()
    assert source.exists("documents/old.txt") and source.exists("backups/old.json")
    assert storages["private_documents"].listdir("") == ([], [])
    assert storages["private_backups"].listdir("") == ([], [])


def test_kopia_dokumentow_zachowuje_nazwy_i_rekord(legacy):
    source, document = legacy
    run(kind="documents", apply=True)
    target = storages["private_documents"]
    assert source.exists("documents/old.txt")
    assert target.open("documents/old.txt").read() == b"LEGACY_PRIVATE_CONTENT"
    document.refresh_from_db()
    assert document.file.name == "documents/old.txt"


def test_usuniecie_po_weryfikacji_i_powtorzenie_sa_bezpieczne(legacy, settings):
    source, document = legacy
    run(apply=True, delete_source=True)
    run(apply=True, delete_source=True)
    assert not source.exists("documents/old.txt")
    assert not source.exists("backups/old.json")
    assert source.exists("widget_branding/logo.svg")
    settings.ALLOW_LEGACY_DOCUMENT_READS = False
    with document.file.open("rb") as stream:
        assert stream.read() == b"LEGACY_PRIVATE_CONTENT"


def test_backup_przechodzi_szyfrowanie_i_odtworzenie(legacy):
    source, _ = legacy
    run(kind="backups", apply=True)
    target = storages["private_backups"]
    _, names = target.listdir("backups/migrated")
    assert len(names) == 1
    encrypted = target.open("backups/migrated/" + names[0]).read()
    assert b"PRIVATE" not in encrypted
    assert decrypt_backup(encrypted) == source.open("backups/old.json").read()


def test_inny_istniejacy_cel_nie_jest_nadpisany(legacy):
    source, _ = legacy
    target = storages["private_documents"]
    target.save("documents/old.txt", ContentFile(b"DIFFERENT"))
    with pytest.raises(CommandError, match="inną zawartość"):
        run(kind="documents", apply=True, delete_source=True)
    assert source.exists("documents/old.txt")
    assert target.open("documents/old.txt").read() == b"DIFFERENT"


def test_uszkodzona_kopia_nie_kasuje_zrodla(legacy, monkeypatch):
    source, _ = legacy
    target = storages["private_documents"]
    original = target.save
    monkeypatch.setattr(
        target, "save", lambda name, data: original(name, ContentFile(b"CORRUPTED"))
    )
    with pytest.raises(CommandError, match="Niezgodna suma"):
        run(kind="documents", apply=True, delete_source=True)
    assert source.exists("documents/old.txt")
    assert not target.exists("documents/old.txt")


def test_niepoprawny_backup_nie_jest_usuwany(legacy):
    source, _ = legacy
    source.delete("backups/old.json")
    source.save("backups/old.json", ContentFile(b"NOT_JSON"))
    with pytest.raises(CommandError, match="JSON"):
        run(kind="backups", apply=True, delete_source=True)
    assert source.exists("backups/old.json")


def test_usuwanie_wymaga_jawnego_apply(legacy):
    with pytest.raises(CommandError, match="wymaga --apply"):
        run(delete_source=True)


def test_brak_zrodla_i_celu_jest_bledem(legacy):
    source, _ = legacy
    source.delete("documents/old.txt")
    with pytest.raises(CommandError, match="obu magazynach"):
        run(kind="documents", apply=True)
