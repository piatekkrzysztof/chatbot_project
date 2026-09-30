"""A03/A05: zapis po usunięciu i niewykonalne ustawienia retencji."""

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from threading import Event
from unittest.mock import patch

import pytest
from django.db import IntegrityError, close_old_connections, connections, transaction
from django.db.models.signals import pre_delete
from django.utils import timezone

from api.tests.test_privacy_api import auth_client
from api.tests.test_widget_chat_stream import make_openai_stream
from api.utils.chat_engine import persist_exchange, stream_chat_message
from chat.lifecycle import RozmowaUsunieta, usun_rozmowe
from chat.models import (
    ChatMessage,
    ChatUsageLog,
    ContactRequest,
    Conversation,
    PromptLog,
    UsunietaRozmowa,
)
from chat.retention import purge_tenant


@pytest.mark.django_db
def test_blad_w_polowie_zapisu_nie_zostawia_czesci_odpowiedzi(tenant):
    rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="test")
    with patch(
        "api.utils.chat_engine.PromptLog.objects.create", side_effect=RuntimeError("awaria")
    ):
        with pytest.raises(RuntimeError):
            persist_exchange(tenant, rozmowa, "odpowiedź", "faq", 3, "test", "pytanie")
    assert not rozmowa.messages.exists()
    assert not rozmowa.chatusagelog_set.exists()


def osobno(fn):
    close_old_connections()
    try:
        return fn()
    finally:
        connections.close_all()


@pytest.mark.django_db(transaction=True)
def test_usuwanie_czeka_na_caly_zapis_odpowiedzi(tenant):
    rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="test")
    zatrzymany, kontynuuj, ruszylo_usuwanie = Event(), Event(), Event()
    oryginal = PromptLog.objects.create

    def opozniony_zapis(**kwargs):
        zatrzymany.set()
        assert kontynuuj.wait(10)
        return oryginal(**kwargs)

    def usun():
        ruszylo_usuwanie.set()
        return usun_rozmowe(tenant, rozmowa.session_id)

    with (
        patch("api.utils.chat_engine.PromptLog.objects.create", side_effect=opozniony_zapis),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        zapis = pool.submit(
            osobno,
            lambda: persist_exchange(tenant, rozmowa, "odpowiedź", "faq", 3, "test", "pytanie"),
        )
        try:
            assert zatrzymany.wait(5)
            kasowanie = pool.submit(osobno, usun)
            assert ruszylo_usuwanie.wait(5)
            with pytest.raises(TimeoutError):
                kasowanie.result(timeout=0.2)
        finally:
            kontynuuj.set()
        zapis.result(10)
        assert kasowanie.result(10)["PromptLog"] == 1
    assert not Conversation.objects.filter(pk=rozmowa.pk).exists()
    assert not PromptLog.objects.filter(tenant=tenant).exists()
    assert not ChatUsageLog.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "wartosc", [True, False, 1.5, 30.0, 2_147_483_647, 3651, "1.5", None, [], {}]
)
def test_retencja_odrzuca_niewykonalne_wartosci(user, tenant, wartosc):
    wynik = auth_client(user, tenant).patch(
        "/api/privacy/", {"data_retention_days": wartosc}, format="json"
    )
    assert wynik.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("wartosc", [0, 1, 3650, "30"])
def test_poprawna_retencja_i_jej_granice(user, tenant, wartosc):
    wynik = auth_client(user, tenant).patch(
        "/api/privacy/", {"data_retention_days": wartosc}, format="json"
    )
    assert wynik.status_code == 200
    tenant.refresh_from_db()
    assert tenant.data_retention_days == int(wartosc)


@pytest.mark.django_db
def test_baza_odrzuca_wartosc_spoza_zakresu(tenant):
    with pytest.raises(IntegrityError), transaction.atomic():
        type(tenant).objects.filter(pk=tenant.pk).update(data_retention_days=3651)


@pytest.mark.django_db
def test_blad_kasowania_cofa_caly_graf_i_znacznik(user, tenant):
    rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="test")
    persist_exchange(tenant, rozmowa, "odpowiedź", "faq", 3, "test", "pytanie")
    ContactRequest.objects.create(tenant=tenant, conversation=rozmowa, contact="test@example.test")

    def awaria(**kwargs):
        raise RuntimeError("awaria kasowania")

    pre_delete.connect(awaria, sender=ContactRequest, weak=False)
    try:
        with pytest.raises(RuntimeError):
            auth_client(user, tenant).delete(f"/api/privacy/conversations/{rozmowa.session_id}/")
    finally:
        pre_delete.disconnect(awaria, sender=ContactRequest)
    assert Conversation.objects.filter(pk=rozmowa.pk).exists()
    assert PromptLog.objects.filter(conversation=rozmowa).count() == 1
    assert not UsunietaRozmowa.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "model,fields",
    [
        (PromptLog, {"model": "test", "prompt": "x", "source": "faq"}),
        (ChatUsageLog, {"tokens_used": 1}),
        (ContactRequest, {"contact": "test@example.test"}),
    ],
)
def test_spozniony_zapis_nie_staje_sie_osieroconym_logiem(tenant, model, fields):
    rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="test")
    usun_rozmowe(tenant, rozmowa.session_id)
    with pytest.raises(RozmowaUsunieta):
        model.objects.create(tenant=tenant, conversation=rozmowa, **fields)
    assert not model.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url", ["/api/widget/chat/", "/api/widget/chat/stream/", "/api/widget/contact/"]
)
def test_ponowienie_usunietej_sesji_nie_odtwarza_danych(tenant, subscribtion, url):
    from rest_framework.test import APIClient

    rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="test")
    usun_rozmowe(tenant, rozmowa.session_id)
    with patch("api.utils.chat_engine.get_client") as ai:
        wynik = APIClient().post(
            url,
            {
                "message": "stare pytanie",
                "contact": "test@example.test",
                "conversation_session_id": str(rozmowa.session_id),
            },
            format="json",
            HTTP_X_API_KEY=str(tenant.api_key),
        )
        assert wynik.status_code == 410
        ai.assert_not_called()
    assert not Conversation.objects.filter(tenant=tenant).exists()
    assert not ContactRequest.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_usuniecie_podczas_sse_zamyka_ai_i_nie_zapisuje_fragmentow(tenant):
    rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="test")

    class Provider:
        closed = False

        def __iter__(self):
            yield make_openai_stream(["pierwszy"])[0]
            usun_rozmowe(tenant, rozmowa.session_id)
            yield make_openai_stream(["drugi"])[0]

        def close(self):
            self.closed = True

    provider = Provider()
    with (
        patch("api.utils.chat_engine.get_client") as ai,
        patch("api.utils.chat_engine.build_chat_messages", return_value=([], [], [], False)),
        patch("api.utils.chat_engine.time.monotonic", side_effect=[0, 1, 2]),
    ):
        ai.return_value.chat.completions.create.return_value = provider
        events = [json.loads(s[6:]) for s in stream_chat_message(tenant, rozmowa, "pytanie")]
    assert provider.closed
    assert [e["type"] for e in events] == ["delta", "error"]
    assert events[-1]["code"] == "conversation_deleted"
    assert not PromptLog.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_zamkniecie_sse_po_usunieciu_nie_ignoruje_generator_exit(tenant):
    rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="test")
    with (
        patch("api.utils.chat_engine.get_client") as ai,
        patch("api.utils.chat_engine.build_chat_messages", return_value=([], [], [], False)),
    ):
        ai.return_value.chat.completions.create.return_value = iter(
            make_openai_stream(["pierwszy", "drugi"])
        )
        stream = stream_chat_message(tenant, rozmowa, "pytanie")
        next(stream)
        usun_rozmowe(tenant, rozmowa.session_id)
        stream.close()
    assert not PromptLog.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_retencja_zachowuje_swiezy_kontakt_i_blokuje_odtworzenie_starej_sesji(tenant):
    tenant.data_retention_days = 30
    tenant.save()
    rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="test")
    ContactRequest.objects.create(tenant=tenant, conversation=rozmowa, contact="a@example.test")
    Conversation.objects.filter(pk=rozmowa.pk).update(
        last_message_at=timezone.now() - timedelta(days=40)
    )
    purge_tenant(tenant)
    assert Conversation.objects.filter(pk=rozmowa.pk).exists()
    ContactRequest.objects.filter(conversation=rozmowa).update(
        created_at=timezone.now() - timedelta(days=40)
    )
    purge_tenant(tenant)
    assert not Conversation.objects.filter(pk=rozmowa.pk).exists()
    assert UsunietaRozmowa.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db(transaction=True)
def test_migracja_odmawia_zlej_retencji_bez_zmiany_danych():
    from io import StringIO

    from django.core.management import call_command
    from django.core.management.base import CommandError
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    old = [("accounts", "0042_kontrola_stripe")]
    executor.migrate(old)
    Tenant = executor.loader.project_state(old).apps.get_model("accounts", "Tenant")
    tenant = Tenant.objects.create(name="Preflight test", data_retention_days=2_147_483_647)
    try:
        out = StringIO()
        with pytest.raises(CommandError):
            call_command("kontrola_retencji", stdout=out)
        assert str(tenant.pk) in out.getvalue()
        with pytest.raises(RuntimeError, match="Retencja poza zakresem"):
            MigrationExecutor(connection).migrate(latest)
        tenant.refresh_from_db()
        assert tenant.data_retention_days == 2_147_483_647
    finally:
        Tenant.objects.filter(pk=tenant.pk).update(data_retention_days=90)
        MigrationExecutor(connection).migrate(latest)


@pytest.mark.django_db
def test_kontakt_przed_pierwsza_wiadomoscia_znika_z_sesja(tenant):
    from uuid import uuid4

    from rest_framework.test import APIClient

    session_id = uuid4()
    wynik = APIClient().post(
        "/api/widget/contact/",
        {"contact": "a@example.test", "conversation_session_id": str(session_id)},
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
    )
    assert wynik.status_code == 201
    assert ContactRequest.objects.get().conversation.session_id == session_id
    usun_rozmowe(tenant, session_id)
    assert not ContactRequest.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_sesja_i_zapis_obcej_firmy_sa_odrzucane(tenant):
    from api.tests.factories import TenantFactory
    from chat.lifecycle import otworz_rozmowe

    inna = TenantFactory()
    rozmowa = Conversation.objects.create(tenant=inna, user_identifier="obca")
    with pytest.raises(RozmowaUsunieta):
        otworz_rozmowe(tenant=tenant, session_id=rozmowa.session_id, defaults={})
    with pytest.raises(RozmowaUsunieta):
        ContactRequest.objects.create(tenant=tenant, conversation=rozmowa, contact="x@example.test")
    assert usun_rozmowe(tenant, rozmowa.session_id) is None
    assert Conversation.objects.filter(pk=rozmowa.pk).exists()


@pytest.mark.django_db
def test_usuniecie_po_pracy_ai_nie_zwraca_odpowiedzi_ani_nie_cofa_naliczenia(tenant, subscribtion):
    from rest_framework.test import APIClient

    rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="test")

    def model(*args, **kwargs):
        usun_rozmowe(tenant, rozmowa.session_id)
        return {"content": "usunięta odpowiedź", "tokens": 5}

    with (
        patch("api.utils.chat_engine.get_openai_response", side_effect=model),
        patch("api.utils.chat_engine.build_chat_messages", return_value=([], [], [], False)),
    ):
        wynik = APIClient().post(
            "/api/widget/chat/",
            {"message": "pytanie", "conversation_session_id": str(rozmowa.session_id)},
            format="json",
            HTTP_X_API_KEY=str(tenant.api_key),
        )
    assert wynik.status_code == 410
    subscribtion.refresh_from_db()
    assert subscribtion.current_message_count == 1
    assert not PromptLog.objects.filter(tenant=tenant).exists()
    assert not ChatMessage.objects.filter(conversation_id=rozmowa.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_zapis_i_otwarcie_czekaja_na_usuniecie_i_odmawiaja_po_commit(tenant):
    from chat.lifecycle import otworz_rozmowe

    rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="test")
    zatrzymany, kontynuuj = Event(), Event()
    zapis_ruszyl, otwarcie_ruszylo = Event(), Event()

    def w_trakcie(sender, instance, **kwargs):
        if instance.pk == rozmowa.pk:
            zatrzymany.set()
            assert kontynuuj.wait(10)

    def zapisz():
        zapis_ruszyl.set()
        with pytest.raises(RozmowaUsunieta):
            persist_exchange(tenant, rozmowa, "spóźniona", "faq", 1, "test", "pytanie")

    def otworz():
        otwarcie_ruszylo.set()
        with pytest.raises(RozmowaUsunieta):
            otworz_rozmowe(tenant=tenant, session_id=rozmowa.session_id, defaults={})

    pre_delete.connect(w_trakcie, sender=Conversation, weak=False)
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            kasowanie = pool.submit(osobno, lambda: usun_rozmowe(tenant, rozmowa.session_id))
            try:
                assert zatrzymany.wait(5)
                zapis = pool.submit(osobno, zapisz)
                otwarcie = pool.submit(osobno, otworz)
                assert zapis_ruszyl.wait(5) and otwarcie_ruszylo.wait(5)
                for future in (zapis, otwarcie):
                    with pytest.raises(TimeoutError):
                        future.result(timeout=0.2)
            finally:
                kontynuuj.set()
            kasowanie.result(10)
            zapis.result(10)
            otwarcie.result(10)
    finally:
        pre_delete.disconnect(w_trakcie, sender=Conversation)
    assert not Conversation.objects.filter(tenant=tenant).exists()
    assert not PromptLog.objects.filter(tenant=tenant).exists()
    assert UsunietaRozmowa.objects.filter(tenant=tenant).count() == 1


@pytest.mark.django_db
def test_dry_run_nie_zglasza_rozmowy_ze_swiezym_kontaktem(tenant):
    from io import StringIO

    from django.core.management import call_command

    rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="test")
    ContactRequest.objects.create(tenant=tenant, conversation=rozmowa, contact="a@example.test")
    Conversation.objects.filter(pk=rozmowa.pk).update(
        last_message_at=timezone.now() - timedelta(days=400)
    )
    out = StringIO()
    call_command("purge_expired_data", dry_run=True, stdout=out)
    assert "Conversation=1" not in out.getvalue()
    assert "nic do usunięcia" in out.getvalue()
    assert Conversation.objects.filter(pk=rozmowa.pk).exists()
