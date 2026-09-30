"""A04: trwałość zleceń, rollback, ponowienia i granice magazynów."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from io import StringIO
from threading import Event
from unittest.mock import patch

import pytest
from django.apps import apps
from django.core import mail
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management import CommandError, call_command
from django.db import close_old_connections, connections, transaction
from django.utils import timezone

from accounts.models import Tenant
from chatbot_project.pliki import _obudz as obudz_zlecenie
from documents.models import Document, UsunieciePliku
from documents.usuwanie_plikow import (
    MAX_PROB,
    BlokadaUsuniecia,
    alarmuj,
    cel_magazynu,
    ponow_usuniecie,
    usun_oczekujace_pliki,
    wykonaj_usuniecie,
)


@pytest.fixture(autouse=True)
def lokalne_pliki(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "public")
    settings.PRIVATE_MEDIA_ROOT = str(tmp_path / "private")


@pytest.mark.django_db
def test_utrata_callbacku_nie_gubi_zlecenia(tenant, django_capture_on_commit_callbacks):
    doc = Document.objects.create(tenant=tenant, name="test", processed=True)
    doc.file.save("a.txt", ContentFile(b"test"))
    nazwa = doc.file.name
    with django_capture_on_commit_callbacks(execute=False):
        doc.delete()
    Job = apps.get_model("documents", "UsunieciePliku")
    assert Job.objects.filter(nazwa=nazwa, stan="oczekuje").exists()
    assert storages["private_documents"].exists(nazwa)


@pytest.mark.django_db(transaction=True)
def test_blad_zapisu_logo_zostawia_stary_plik():
    firma = Tenant.objects.create(name="test")
    firma.widget_logo.save("old.png", ContentFile(b"stare"))
    stara = firma.widget_logo.name
    firma.widget_logo = ContentFile(b"nowe", name="new.png")
    with patch.object(Tenant, "_do_update", side_effect=RuntimeError("awaria zapisu")):
        with pytest.raises(RuntimeError):
            firma.save(update_fields=["widget_logo"])
    firma.refresh_from_db()
    assert firma.widget_logo.name == stara
    assert storages["default"].exists(stara)


@pytest.fixture(autouse=True)
def bez_brokera(monkeypatch):
    monkeypatch.setattr("chatbot_project.pliki._obudz", lambda *args: None)


def przygotuj(tenant):
    doc = Document.objects.create(tenant=tenant, name="test", processed=True)
    doc.file.save("a.txt", ContentFile(b"test"))
    doc.delete()
    return UsunieciePliku.objects.latest("pk")


@pytest.mark.django_db
def test_ponowienie_po_awarii_i_odstep_do_kolejnej_proby(tenant, caplog):
    job = przygotuj(tenant)
    with patch.object(
        storages["private_documents"], "delete", side_effect=OSError("sekret-nie-loguj")
    ) as delete:
        assert wykonaj_usuniecie(job.pk)
        assert not wykonaj_usuniecie(job.pk)
        assert delete.call_count == 1
    job.refresh_from_db()
    assert job.stan == "oczekuje" and job.proby == 1
    assert job.ponow_at > timezone.now()
    assert "sekret-nie-loguj" not in caplog.text
    assert job.nazwa not in caplog.text
    UsunieciePliku.objects.filter(pk=job.pk).update(ponow_at=timezone.now())
    assert wykonaj_usuniecie(job.pk)
    job.refresh_from_db()
    assert job.stan == "gotowe" and job.proby == 2
    assert not storages["private_documents"].exists(job.nazwa)


@pytest.mark.django_db(transaction=True)
def test_obchod_odzyskuje_zlecenie_po_utracie_callbacku(tenant):
    job = przygotuj(tenant)
    assert storages["private_documents"].exists(job.nazwa)
    usun_oczekujace_pliki()
    job.refresh_from_db()
    assert job.stan == "gotowe"


@pytest.mark.django_db
def test_wycofanie_usuwa_rowniez_zlecenie(tenant):
    doc = Document.objects.create(tenant=tenant, name="test", processed=True)
    doc.file.save("a.txt", ContentFile(b"test"))
    pk, nazwa = doc.pk, doc.file.name
    with pytest.raises(RuntimeError), transaction.atomic():
        doc.delete()
        raise RuntimeError("rollback")
    assert Document.objects.filter(pk=pk).exists()
    assert not UsunieciePliku.objects.exists()
    assert storages["private_documents"].exists(nazwa)


@pytest.mark.django_db(transaction=True)
def test_awaria_zapisu_zlecenia_cofa_usuniecie_rekordu(tenant):
    doc = Document.objects.create(tenant=tenant, name="test", processed=True)
    doc.file.save("a.txt", ContentFile(b"test"))
    pk = doc.pk
    with patch.object(UsunieciePliku, "save", side_effect=RuntimeError("baza")):
        with pytest.raises(RuntimeError):
            doc.delete()
    assert Document.objects.filter(pk=pk).exists()
    assert storages["private_documents"].exists(doc.file.name)


@pytest.mark.django_db
def test_zlecenia_przezywaja_usuniecie_firmy(tenant):
    doc = Document.objects.create(tenant=tenant, name="test", processed=True)
    doc.file.save("a.txt", ContentFile(b"test"))
    tenant.widget_logo.save("logo.png", ContentFile(b"logo"))
    firma_id = tenant.pk
    tenant.delete()
    assert UsunieciePliku.objects.filter(firma_id=firma_id).count() == 2
    usun_oczekujace_pliki()
    assert set(UsunieciePliku.objects.values_list("stan", flat=True)) == {"gotowe"}


@pytest.mark.django_db
@pytest.mark.parametrize("juz_skasowany", [True, False])
def test_wygasla_dzierzawa_odzyskuje_zadanie_i_toleruje_brak_pliku(tenant, juz_skasowany):
    job = przygotuj(tenant)
    if juz_skasowany:
        storages["private_documents"].delete(job.nazwa)
    UsunieciePliku.objects.filter(pk=job.pk).update(
        stan="praca", proby=1, dzierzawa_do=timezone.now() - timedelta(seconds=1)
    )
    assert wykonaj_usuniecie(job.pk)
    job.refresh_from_db()
    assert job.stan == "gotowe" and job.proby == 2


@pytest.mark.django_db
def test_wyczerpane_proby_wymagaja_recznej_reakcji(tenant):
    job = przygotuj(tenant)
    with patch.object(
        storages["private_documents"], "delete", side_effect=OSError("offline")
    ) as delete:
        for _ in range(MAX_PROB):
            UsunieciePliku.objects.filter(pk=job.pk).update(ponow_at=timezone.now())
            wykonaj_usuniecie(job.pk)
        assert not wykonaj_usuniecie(job.pk)
        assert delete.call_count == MAX_PROB
    job.refresh_from_db()
    assert job.stan == "blad"
    ponow_usuniecie(job.pk)
    assert wykonaj_usuniecie(job.pk)
    with pytest.raises(BlokadaUsuniecia):
        ponow_usuniecie(job.pk)


@pytest.mark.django_db
def test_zmiana_magazynu_blokuje_zlecenie(tenant, settings, tmp_path):
    job = przygotuj(tenant)
    settings.PRIVATE_MEDIA_ROOT = str(tmp_path / "inny")
    nowy = storages["private_documents"]
    nowy.save(job.nazwa, ContentFile(b"NIE KASUJ"))
    wykonaj_usuniecie(job.pk)
    job.refresh_from_db()
    assert job.stan == "blad" and job.blad == "zmieniony_magazyn"
    assert nowy.exists(job.nazwa)
    with pytest.raises(BlokadaUsuniecia, match="zmieniony_magazyn"):
        ponow_usuniecie(job.pk)


@pytest.mark.django_db
def test_wspoldzielony_plik_czeka_na_ostatnie_odwolanie_bez_alarmu(tenant):
    tenant.widget_logo.save("logo.png", ContentFile(b"logo"))
    nazwa = tenant.widget_logo.name
    tenant.widget_avatar = nazwa
    tenant.save(update_fields=["widget_avatar"])
    tenant.widget_logo = ""
    tenant.save(update_fields=["widget_logo"])
    usun_oczekujace_pliki()
    assert storages["default"].exists(nazwa)
    assert UsunieciePliku.objects.get().stan == "zachowany"
    assert not mail.outbox
    tenant.widget_avatar = ""
    tenant.save(update_fields=["widget_avatar"])
    usun_oczekujace_pliki()
    assert not storages["default"].exists(nazwa)


@pytest.mark.django_db
def test_odwolanie_innej_firmy_tez_chroni_plik(tenant):
    doc = Document.objects.create(tenant=tenant, name="test", processed=True)
    doc.file.save("a.txt", ContentFile(b"test"))
    other = Tenant.objects.create(name="inna")
    Document.objects.create(tenant=other, name="inny", file=doc.file.name, processed=True)
    nazwa = doc.file.name
    doc.delete()
    usun_oczekujace_pliki()
    assert storages["private_documents"].exists(nazwa)


@pytest.mark.django_db
def test_wymiana_dokumentu_zleca_usuniecie_poprzedniego(tenant):
    doc = Document.objects.create(tenant=tenant, name="test", processed=True)
    doc.file.save("a.txt", ContentFile(b"test"))
    stara = doc.file.name
    doc.file.save("a.txt", ContentFile(b"nowe"))
    usun_oczekujace_pliki()
    assert not storages["private_documents"].exists(stara)
    assert storages["private_documents"].exists(doc.file.name)


@pytest.mark.django_db
def test_alarm_jest_ograniczony_i_nie_zawiera_sciezek(tenant, settings):
    settings.EMAIL_ALERTOW = "operator@example.test"
    job = przygotuj(tenant)
    UsunieciePliku.objects.filter(pk=job.pk).update(
        utworzono_at=timezone.now() - timedelta(minutes=16)
    )
    assert alarmuj() == 1
    assert alarmuj() == 0
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["operator@example.test"]
    assert job.nazwa not in mail.outbox[0].body
    assert f"Zlecenie {job.pk}" in mail.outbox[0].body


@pytest.mark.django_db
def test_awaria_smtp_nie_wycisza_alarmu(tenant, settings):
    settings.EMAIL_ALERTOW = "operator@example.test"
    job = przygotuj(tenant)
    UsunieciePliku.objects.filter(pk=job.pk).update(stan="blad")
    with patch("documents.usuwanie_plikow.send_mail", return_value=0):
        assert alarmuj() == 0
    job.refresh_from_db()
    assert job.alarm_at is None
    assert alarmuj() == 1


@pytest.mark.django_db
def test_komenda_domyslnie_tylko_raportuje(tenant):
    job = przygotuj(tenant)
    UsunieciePliku.objects.filter(pk=job.pk).update(stan="blad")
    out = StringIO()
    with pytest.raises(CommandError):
        call_command("kontrola_usuwania_plikow", stdout=out)
    assert job.nazwa not in out.getvalue()
    assert storages["private_documents"].exists(job.nazwa)
    call_command("kontrola_usuwania_plikow", ponow=job.pk, stdout=out)
    job.refresh_from_db()
    assert job.stan == "oczekuje"
    assert storages["private_documents"].exists(job.nazwa)


def osobno(fn):
    close_old_connections()
    try:
        return fn()
    finally:
        connections.close_all()


@pytest.mark.django_db(transaction=True)
def test_dwa_workery_nie_wykonuja_tej_samej_aktywnej_proby(tenant):
    job = przygotuj(tenant)
    wszedl, zakoncz = Event(), Event()
    original = storages["private_documents"].delete

    def wolno(name):
        wszedl.set()
        assert zakoncz.wait(10)
        original(name)

    with patch.object(storages["private_documents"], "delete", side_effect=wolno) as delete:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pierwszy = pool.submit(osobno, lambda: wykonaj_usuniecie(job.pk))
            try:
                assert wszedl.wait(5)
                drugi = pool.submit(osobno, lambda: wykonaj_usuniecie(job.pk))
                assert drugi.result(5) is False
            finally:
                zakoncz.set()
            assert pierwszy.result(10)
        assert delete.call_count == 1


@pytest.mark.django_db
def test_blad_brokera_nie_gubi_trwalego_zlecenia(tenant):
    job = przygotuj(tenant)
    with patch("documents.usuwanie_plikow.usun_zlecony_plik.apply_async", side_effect=OSError()):
        obudz_zlecenie(job.pk, "default")
    assert storages["private_documents"].exists(job.nazwa)
    usun_oczekujace_pliki()
    job.refresh_from_db()
    assert job.stan == "gotowe"


@pytest.mark.django_db
def test_stary_worker_nie_potwierdza_cudzej_proby(tenant):
    import uuid

    job = przygotuj(tenant)
    newer = uuid.uuid4()

    def przerwana_proba(name):
        UsunieciePliku.objects.filter(pk=job.pk).update(token=newer)

    with patch.object(storages["private_documents"], "delete", side_effect=przerwana_proba):
        wykonaj_usuniecie(job.pk)
    job.refresh_from_db()
    assert job.stan == "praca" and job.token == newer


@pytest.mark.django_db
def test_sprzatanie_sladow_nie_kasuje_zaleglosci(tenant):
    job = przygotuj(tenant)
    wykonaj_usuniecie(job.pk)
    UsunieciePliku.objects.filter(pk=job.pk).update(
        zakonczono_at=timezone.now() - timedelta(days=31)
    )
    failed = przygotuj(tenant)
    UsunieciePliku.objects.filter(pk=failed.pk).update(
        stan="blad", utworzono_at=timezone.now() - timedelta(days=31)
    )
    with patch("documents.usuwanie_plikow.alarmuj"):
        usun_oczekujace_pliki()
    assert not UsunieciePliku.objects.filter(pk=job.pk).exists()
    assert UsunieciePliku.objects.filter(pk=failed.pk).exists()


def test_s3_tozsamosc_celu_nie_zalezy_od_kluczy_i_usuwanie_ma_timeout(settings):
    from documents.usuwanie_plikow import _magazyn_do_usuwania

    settings.STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": "synthetic-bucket",
                "access_key": "synthetic-first",
                "secret_key": "synthetic-first",
                "endpoint_url": "https://storage.example.test",
            },
        }
    }
    first = cel_magazynu("default")
    storages["default"].access_key = "synthetic-second"
    storages["default"].secret_key = "synthetic-second"
    assert cel_magazynu("default") == first
    bounded = _magazyn_do_usuwania("default")
    assert bounded.client_config.connect_timeout == 5
    assert bounded.client_config.read_timeout == 10
    storages["default"].bucket_name = "other-bucket"
    assert cel_magazynu("default") != first


@pytest.mark.django_db(transaction=True)
def test_rownolegla_wymiana_logo_zachowuje_ostatni_plik_i_sprzata_obie_stare_wersje(tenant):
    tenant.widget_logo.save("old.png", ContentFile(b"old"))
    old = tenant.widget_logo.name
    first_at_update, release_first, second_started = Event(), Event(), Event()
    original = Tenant._do_update

    def pause_first(instance, *args, **kwargs):
        if getattr(instance, "_test_first", False):
            first_at_update.set()
            assert release_first.wait(10)
        return original(instance, *args, **kwargs)

    def replace(first):
        instance = Tenant.objects.get(pk=tenant.pk)
        instance._test_first = first
        instance.widget_logo = ContentFile(b"first" if first else b"second", name="same.png")
        if not first:
            second_started.set()
        instance.save(update_fields=["widget_logo"])
        return instance.widget_logo.name

    with patch.object(Tenant, "_do_update", pause_first):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(osobno, lambda: replace(True))
            try:
                assert first_at_update.wait(5)
                second = pool.submit(osobno, lambda: replace(False))
                assert second_started.wait(5)
                with pytest.raises(TimeoutError):
                    second.result(timeout=0.2)
            finally:
                release_first.set()
            first_name, second_name = first.result(10), second.result(10)
    assert set(UsunieciePliku.objects.values_list("nazwa", flat=True)) == {old, first_name}
    usun_oczekujace_pliki()
    tenant.refresh_from_db()
    assert tenant.widget_logo.name == second_name
    assert tenant.widget_logo.read() == b"second"
    assert not storages["default"].exists(old)
    assert not storages["default"].exists(first_name)


@pytest.mark.django_db
def test_stary_dokument_sprzata_obie_lokalizacje_podczas_migracji(tenant, settings):
    settings.ALLOW_LEGACY_DOCUMENT_READS = True
    name = "documents/legacy.txt"
    for alias in ("default", "private_documents"):
        storages[alias].save(name, ContentFile(b"legacy"))
    Document.objects.create(tenant=tenant, file=name, processed=True).delete()
    assert set(UsunieciePliku.objects.values_list("magazyn", flat=True)) == {
        "default",
        "private_documents",
    }
    usun_oczekujace_pliki()
    assert all(not storages[a].exists(name) for a in ("default", "private_documents"))


@pytest.mark.django_db
def test_uszkodzona_nazwa_zlecenia_nie_dociera_do_magazynu(tenant):
    job = przygotuj(tenant)
    UsunieciePliku.objects.filter(pk=job.pk).update(nazwa="../other-secret")
    with patch.object(storages["private_documents"], "delete") as delete:
        wykonaj_usuniecie(job.pk)
    delete.assert_not_called()
    job.refresh_from_db()
    assert job.stan == "blad" and job.blad == "nieprawidlowa_nazwa"


@pytest.mark.django_db
def test_blad_uprawnien_ma_bezpieczny_kod_bez_odpowiedzi_dostawcy(tenant, caplog):
    from botocore.exceptions import ClientError

    job = przygotuj(tenant)
    error = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "SECRET_SENTINEL"}}, "DeleteObject"
    )
    with patch.object(storages["private_documents"], "delete", side_effect=error):
        wykonaj_usuniecie(job.pk)
    job.refresh_from_db()
    assert job.blad == "brak_uprawnien"
    assert "SECRET_SENTINEL" not in caplog.text


def test_porownanie_magazynow_pokazuje_tylko_aliasy_i_skroty():
    output = StringIO()
    call_command("kontrola_usuwania_plikow", magazyny=True, stdout=output)
    assert output.getvalue().splitlines() == [
        f"{alias} cel={cel_magazynu(alias)}" for alias in ("default", "private_documents")
    ]
