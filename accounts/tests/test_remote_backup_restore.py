"""Rzeczywisty dump i odtworzenie PostgreSQL; magazyn obiektowy jest atrapą."""

import pytest
from django.core.management import call_command

from accounts.models import CustomUser, Tenant
from accounts.tests.test_backup_monitoring import remote_backups
from accounts.tests.test_odtwarzanie import _policz_wszystko, dane_do_odtworzenia
from documents.models import DocumentChunk
from documents.wymiar import WYMIAR_WEKTORA


@pytest.mark.django_db(transaction=True)
def test_verified_remote_backup_restores_relations_passwords_keys_and_vectors(
    remote_backups, dane_do_odtworzenia, tmp_path, monkeypatch
):
    before = _policz_wszystko()
    api_key = dane_do_odtworzenia["firma"].api_key
    call_command("backup_data", to_storage=True)
    call_command("check_backup")
    encrypted = tmp_path / "downloaded.fernet"
    encrypted.write_bytes(next(iter(remote_backups.values())))
    plaintext = tmp_path / "restore.json"
    call_command("decrypt_backup", str(encrypted), output=str(plaintext))

    call_command("flush", interactive=False, verbosity=0)

    def no_paid_work(*args, **kwargs):
        raise AssertionError("Odtworzenie nie może zlecać przetwarzania dokumentów.")

    for name in (
        "embed_document_task",
        "extract_text_from_document",
        "generate_embeddings_for_document",
    ):
        monkeypatch.setattr(f"documents.tasks.{name}.delay", no_paid_work)
    call_command("loaddata", str(plaintext), verbosity=0)
    assert _policz_wszystko() == before
    assert Tenant.objects.get().api_key == api_key
    assert CustomUser.objects.get().check_password("tajne-haslo-2026")
    chunk = DocumentChunk.objects.get()
    assert len(chunk.embedding) == WYMIAR_WEKTORA
    assert chunk.embedding[0] == pytest.approx(0.5)
    assert chunk.embedding[-1] == pytest.approx(0.25)
