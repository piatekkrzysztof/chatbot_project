"""Backup zawiera dane i sekrety całej aplikacji — zapis musi być szyfrowany."""

import pytest
from cryptography.fernet import Fernet
from django.core.files.storage import storages
from django.core.management import CommandError, call_command

from accounts.backups import MAGIC, decrypt_backup, encrypt_backup


@pytest.mark.django_db
def test_kopia_na_dysku_nie_zawiera_jawnych_danych(tenant, settings, tmp_path):
    settings.BACKUP_ENCRYPTION_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    path = tmp_path / "kopia.fernet"
    call_command("backup_data", output=str(path))
    assert tenant.name.encode() not in path.read_bytes()
    assert b"accounts.tenant" not in path.read_bytes()


@pytest.mark.django_db
def test_brak_klucza_nie_zapisuje_kopii(tenant, settings, tmp_path):
    settings.BACKUP_ENCRYPTION_KEY = ""
    path = tmp_path / "kopia.fernet"
    with pytest.raises(CommandError, match="BACKUP_ENCRYPTION_KEY"):
        call_command("backup_data", output=str(path))
    assert not path.exists()


def test_odtworzenie_sprawdza_integralnosc(settings):
    plaintext = b'[{"model": "accounts.tenant", "pk": 1, "fields": {"name": "PRIVATE"}}]'
    encrypted = encrypt_backup(plaintext)
    assert encrypted.startswith(MAGIC)
    assert decrypt_backup(encrypted) == plaintext
    damaged = bytearray(encrypted)
    damaged[-10] = ord("a") if damaged[-10] != ord("a") else ord("b")
    with pytest.raises(CommandError, match="uszkodzone"):
        decrypt_backup(bytes(damaged))


def test_bledny_klucz_nie_zostawia_pliku(settings, tmp_path):
    path = tmp_path / "backup.fernet"
    path.write_bytes(encrypt_backup(b'[{"model": "synthetic"}]'))
    settings.BACKUP_ENCRYPTION_KEY = Fernet.generate_key().decode()
    output = tmp_path / "plain.json"
    with pytest.raises(CommandError, match="błędny klucz"):
        call_command("decrypt_backup", str(path), output=str(output))
    assert not output.exists()


@pytest.mark.django_db
def test_kopia_nie_nadpisuje_istniejacego_pliku(tenant, tmp_path):
    path = tmp_path / "existing.fernet"
    path.write_bytes(b"EXISTING_BACKUP")
    with pytest.raises(CommandError, match="istnieje"):
        call_command("backup_data", output=str(path))
    assert path.read_bytes() == b"EXISTING_BACKUP"


@pytest.mark.django_db
def test_kopia_nie_moze_trafic_do_publicznego_media(tenant, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "public"
    with pytest.raises(CommandError, match="MEDIA_ROOT"):
        call_command("backup_data", output=str(settings.MEDIA_ROOT / "backup.fernet"))
    assert not settings.MEDIA_ROOT.exists()


@pytest.mark.django_db
def test_to_storage_nie_ma_fallbacku_na_dysk(tenant, tmp_path):
    with pytest.raises(CommandError, match="prywatnego magazynu"):
        call_command("backup_data", to_storage=True, output=str(tmp_path / "backup.fernet"))
    assert not list(tmp_path.iterdir())


@pytest.mark.django_db
def test_to_storage_wysyla_tylko_szyfrogram_bez_lokalnego_pliku(
    tenant, settings, monkeypatch, tmp_path
):
    from chatbot_project.storage import PrivateS3Storage

    settings.STORAGES = {
        **settings.STORAGES,
        "private_backups": {
            "BACKEND": "chatbot_project.storage.PrivateS3Storage",
            "OPTIONS": {"bucket_name": "synthetic", "access_key": "test", "secret_key": "test"},
        },
    }
    saved = []

    def capture(self, name, content, max_length=None):
        saved.append((name, content.read()))
        return name

    monkeypatch.setattr(PrivateS3Storage, "save", capture)
    from django.core.files.base import ContentFile

    monkeypatch.setattr(PrivateS3Storage, "open", lambda *a, **k: ContentFile(saved[-1][1]))
    monkeypatch.chdir(tmp_path)
    call_command("backup_data", to_storage=True)
    assert len(saved) == 1
    assert saved[0][0].endswith(".json.fernet")
    assert tenant.name.encode() not in saved[0][1]
    assert tenant.name.encode() in decrypt_backup(saved[0][1])
    assert not list(tmp_path.iterdir())


@pytest.mark.django_db
def test_limit_kopii_przerywa_przed_zapisem(tenant, settings, tmp_path):
    settings.BACKUP_MAX_BYTES = 20
    with pytest.raises(CommandError, match="limit"):
        call_command("backup_data", output=str(tmp_path / "backup.fernet"))
    assert not list(tmp_path.iterdir())
