import json
import os
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management import CommandError, call_command
from django.utils import timezone

from accounts.models import Tenant
from documents.models import Document, UsunieciePliku
from documents.raport_plikow import Budzet, Obiekt, _s3, raport
from documents.usuwanie_plikow import cel_magazynu

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def isolated(settings, tmp_path, monkeypatch):
    settings.MEDIA_ROOT = str(tmp_path / "public")
    settings.PRIVATE_MEDIA_ROOT = str(tmp_path / "private")
    monkeypatch.setattr("chatbot_project.pliki._obudz", lambda *args: None)


def put(alias, name, age=48):
    storage = storages[alias]
    saved = storage.save(name, ContentFile(b"synthetic-content"))
    old = (timezone.now() - timedelta(hours=age)).timestamp()
    os.utime(storage.path(saved), (old, old))
    return saved


def quantity(result, state):
    return result["stany"][state]["obiekty"]


def test_report_distinguishes_live_fresh_orphan_pending_completed_and_wrong_target(tenant):
    alias = "private_documents"
    linked = put(alias, "private-documents/linked.txt")
    Document.objects.create(tenant=tenant, file=linked, processed=True)
    put(alias, "private-documents/recent.txt", age=1)
    orphan = put(alias, "private-documents/old.txt")
    for state, name, target in (
        ("oczekuje", "pending", cel_magazynu(alias)),
        ("gotowe", "done", cel_magazynu(alias)),
        ("blad", "wrong", "0" * 64),
    ):
        name = put(alias, f"private-documents/{name}.txt")
        UsunieciePliku.objects.create(magazyn=alias, cel=target, nazwa=name, stan=state)
    result = raport(alias)
    assert result["pelny_zakres_prefiksow"]
    assert result["sprawdzone_obiekty"] == 6
    for state in (
        "powiazany",
        "swiezy",
        "do_weryfikacji",
        "zlecenie_usuniecia",
        "zlecenie_zakonczone",
        "zlecenie_inny_cel",
    ):
        assert quantity(result, state) == 1
    assert orphan not in json.dumps(result)
    assert len(result["probka"]) == 5


def test_other_tenant_reference_and_shared_branding_are_not_orphans(tenant):
    alias = "default"
    name = put(alias, "widget_branding/shared.png")
    other = Tenant.objects.create(name="Other", widget_logo=name, widget_avatar=name)
    put(alias, "documents/legacy.txt")
    Document.objects.create(tenant=other, file="documents/legacy.txt", processed=True)
    result = raport(alias)
    assert quantity(result, "powiazany") == 2
    assert quantity(result, "do_weryfikacji") == 0


def test_read_only_never_reads_bodies_deletes_writes_or_creates_jobs(tenant):
    name = put("private_documents", "private-documents/unused.txt")
    storage = storages["private_documents"]
    with (
        patch.object(storage, "open", side_effect=AssertionError("body read")),
        patch.object(storage, "save", side_effect=AssertionError("write")),
        patch.object(storage, "delete", side_effect=AssertionError("delete")),
        patch.object(UsunieciePliku, "save", side_effect=AssertionError("job write")),
    ):
        result = raport("private_documents")
    assert quantity(result, "do_weryfikacji") == 1
    assert storage.exists(name)
    assert not UsunieciePliku.objects.exists()
    assert Tenant.objects.filter(pk=tenant.pk).exists()


def test_backup_and_unknown_prefixes_are_explicitly_outside_scope():
    put("default", "backups/private.json")
    put("default", "full-backups/archive.saas")
    put("default", "unknown/file.txt")
    result = raport("default")
    assert result["pelny_zakres_prefiksow"] and result["sprawdzone_obiekty"] == 0
    assert result["prefiksy"] == ["widget_branding/", "documents/"]


def test_limit_is_incomplete_and_command_does_not_claim_empty_store():
    for index in range(3):
        put("private_documents", f"private-documents/{index}.txt")
    out = StringIO()
    with pytest.raises(CommandError, match="niepełny"):
        call_command("raport_plikow", magazyn="private_documents", limit=2, stdout=out)
    result = json.loads(out.getvalue())
    assert not result["pelny_zakres_prefiksow"]
    assert result["kod"] == "limit_obiektow"
    assert result["sprawdzone_obiekty"] == 2
    assert quantity(result, "do_weryfikacji") == 2


def test_exact_object_limit_can_still_be_complete():
    put("private_documents", "private-documents/a.txt")
    result = raport("private_documents", limit=1)
    assert result["pelny_zakres_prefiksow"] and result["sprawdzone_obiekty"] == 1


def test_sample_limit_does_not_change_counts_and_names_require_explicit_option():
    for index in range(3):
        put("private_documents", f"private-documents/{index}.txt")
    result = raport("private_documents", probka=1, nazwy=True)
    assert quantity(result, "do_weryfikacji") == 3
    assert result["probka_ograniczona"] and len(result["probka"]) == 1
    assert result["probka"][0]["nazwa"].startswith("private-documents/")
    assert not raport("private_documents", probka=0)["probka"]


@pytest.mark.parametrize("status", ["oczekuje", "praca", "blad", "wstrzymane"])
def test_any_unfinished_job_is_not_an_orphan(status):
    name = put("default", "widget_branding/old.png")
    UsunieciePliku.objects.create(
        magazyn="default", cel=cel_magazynu("default"), nazwa=name, stan=status
    )
    assert quantity(raport("default"), "zlecenie_usuniecia") == 1


def test_unconfigured_or_unreadable_store_fails_closed_and_redacts_exceptions(settings):
    settings.STORAGES = {
        "private_documents": {"BACKEND": "chatbot_project.storage.UnconfiguredPrivateStorage"}
    }
    result = raport("private_documents")
    assert result["kod"] == "nieobslugiwany_magazyn"
    with patch("documents.raport_plikow.cel_magazynu", side_effect=OSError("SECRET/path")):
        result = raport("private_documents")
    assert result["kod"] == "blad_odczytu"
    assert "SECRET" not in json.dumps(result)
    assert not result["pelny_zakres_prefiksow"]


def test_time_limit_returns_incomplete_result():
    with patch("documents.raport_plikow.time.monotonic", side_effect=[0, 2]):
        result = raport("default", sekundy=1)
    assert result["kod"] == "limit_czasu"
    assert not result["pelny_zakres_prefiksow"]


def test_invalid_metadata_is_not_an_orphan(monkeypatch):
    monkeypatch.setattr(
        "documents.raport_plikow.obiekty",
        lambda *args: iter([Obiekt("documents/a.txt", 1, None)]),
    )
    assert quantity(raport("default"), "niepewne_metadane") == 1


def test_live_reference_added_during_inventory_is_seen_before_classification(tenant, monkeypatch):
    name = put("default", "documents/parallel.txt")

    def listing(*args):
        yield Obiekt(name, 10, timezone.now() - timedelta(days=2))
        Document.objects.create(tenant=tenant, file=name, processed=True)

    monkeypatch.setattr("documents.raport_plikow.obiekty", listing)
    assert quantity(raport("default"), "powiazany") == 1


def test_no_follow_of_filesystem_symlinks(tmp_path):
    root = tmp_path / "public"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("SECRET")
    root.mkdir(exist_ok=True)
    link = root / "documents"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit creating symlinks")
    result = raport("default", nazwy=True)
    assert quantity(result, "pominiety_specjalny") == 1
    assert "private.txt" not in json.dumps(result)


@pytest.mark.parametrize("params", [{"limit": 0}, {"wiek": 0}, {"sekundy": 301}, {"probka": 1001}])
def test_invalid_limits_fail_before_storage_access(params):
    with patch("documents.raport_plikow.cel_magazynu", side_effect=AssertionError):
        with pytest.raises(ValueError):
            raport("default", **params)


def s3_setup(settings, monkeypatch):
    settings.STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": "synthetic",
                "access_key": "synthetic",
                "secret_key": "synthetic",
                "location": "app",
                "endpoint_url": "https://storage.example.test",
            },
        },
    }
    storage = storages["default"]
    client = Mock(spec=["list_objects_v2"])
    create = Mock(
        return_value=SimpleNamespace(
            connection=SimpleNamespace(meta=SimpleNamespace(client=client))
        )
    )
    monkeypatch.setattr(storages, "create_storage", create)
    return storage, client, create


def test_s3_pagination_uses_scoped_prefixes_and_only_metadata(settings, monkeypatch):
    storage, client, create = s3_setup(settings, monkeypatch)
    now = timezone.now()
    client.list_objects_v2.side_effect = [
        {
            "Contents": [{"Key": "app/documents/one.txt", "Size": 1, "LastModified": now}],
            "IsTruncated": True,
            "NextContinuationToken": "page2",
        },
        {
            "Contents": [{"Key": "app/documents/two.txt", "Size": 2, "LastModified": now}],
            "IsTruncated": False,
        },
    ]
    result = list(_s3(storage, "default", "documents/", Budzet(60, 100)))
    assert [obj.nazwa for obj in result] == ["documents/one.txt", "documents/two.txt"]
    assert [call.kwargs for call in client.list_objects_v2.call_args_list] == [
        {"Bucket": "synthetic", "Prefix": "app/documents/", "MaxKeys": 250},
        {
            "Bucket": "synthetic",
            "Prefix": "app/documents/",
            "MaxKeys": 250,
            "ContinuationToken": "page2",
        },
    ]
    config = create.call_args.args[0]["OPTIONS"]["client_config"]
    assert config.connect_timeout == 5 and config.read_timeout == 10


def test_s3_wrong_prefix_and_lost_page_token_cannot_report_success(settings, monkeypatch):
    storage, client, _ = s3_setup(settings, monkeypatch)
    client.list_objects_v2.return_value = {
        "Contents": [{"Key": "other/private.txt"}],
        "IsTruncated": False,
    }
    result = raport("default")
    assert result["kod"] == "niezgodny_prefiks"
    client.list_objects_v2.return_value = {"IsTruncated": True}
    assert raport("default")["kod"] == "nieprawidlowa_paginacja"


def test_missing_filesystem_root_is_not_a_successful_empty_inventory():
    result = raport("default")
    assert not result["pelny_zakres_prefiksow"]
    assert result["kod"] == "brak_katalogu_magazynu"


def test_database_queries_are_batched_not_per_object(tenant, django_assert_num_queries):
    for index in range(251):
        name = put("private_documents", f"private-documents/{index}.txt")
        # bulk_create is safe here: fixture rows only, no replacements.
        Document.objects.bulk_create([Document(tenant=tenant, file=name, processed=True)])
    with django_assert_num_queries(4):
        result = raport("private_documents", probka=0)
    assert result["sprawdzone_obiekty"] == 251
    assert quantity(result, "powiazany") == 251


def test_command_escapes_control_characters_when_names_are_requested(monkeypatch):
    name = "documents/private\nfilename.txt"
    monkeypatch.setattr(
        "documents.raport_plikow.obiekty",
        lambda *args: iter([Obiekt(name, 3, timezone.now() - timedelta(days=2))]),
    )
    out = StringIO()
    call_command("raport_plikow", magazyn="default", nazwy=True, stdout=out)
    assert json.loads(out.getvalue())["probka"][0]["nazwa"] == name
    assert name not in out.getvalue()
