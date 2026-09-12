"""Admission must precede paid work, including lazy SSE responses."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
from django.db import close_old_connections, connections
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.message_quota import ChatAdmissionDenied, Reservation, reserve_message
from accounts.models import MessageReservation, Subscription
from api.throttles import APIKeyRateThrottle
from chat.models import ChatMessage


def post(tenant, url="/api/widget/chat/stream/"):
    return APIClient().post(
        url,
        {"message": "Dzień dobry", "conversation_session_id": str(uuid.uuid4())},
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
    )


@pytest.mark.django_db(transaction=True)
def test_parallel_requests_cannot_both_start_paid_work(tenant, subscribtion, mocker):
    subscribtion.message_limit = 1
    subscribtion.save()
    entered, release = Event(), Event()

    def model(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return {"content": "Witaj!", "tokens": 1}

    model_call = mocker.patch("api.utils.chat_engine.get_openai_response", side_effect=model)
    mocker.patch("api.utils.chat_engine.build_chat_messages", return_value=([], [], [], False))
    mocker.patch("documents.utils.queue.enqueue")

    def request():
        close_old_connections()
        try:
            return post(tenant, "/api/widget/chat/").status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(request)
        assert entered.wait(10)
        second = pool.submit(request)
        try:
            # A second request must be rejected while the first is still in OpenAI.
            assert second.result(timeout=3) == 429
        finally:
            release.set()
        assert first.result(timeout=10) == 200
    assert model_call.call_count == 1


@pytest.mark.django_db(transaction=True)
def test_unconsumed_stream_holds_last_message(tenant, subscribtion):
    subscribtion.message_limit = 1
    subscribtion.save()
    first = post(tenant)
    try:
        second = post(tenant)
        try:
            assert second.status_code == 429
        finally:
            second.close()
        subscribtion.refresh_from_db()
        assert subscribtion.current_message_count == 0
    finally:
        first.close()


@pytest.mark.django_db(transaction=True)
def test_disconnect_charges_once_and_closes_provider(tenant, subscribtion, mocker):
    provider = mocker.MagicMock()
    provider.__iter__.return_value = iter(
        [
            mocker.Mock(
                usage=None, choices=[mocker.Mock(delta=mocker.Mock(content="Czynne 9-17."))]
            ),
            mocker.Mock(
                usage=None, choices=[mocker.Mock(delta=mocker.Mock(content="Zapraszamy."))]
            ),
        ]
    )
    mocker.patch(
        "api.utils.chat_engine.get_client"
    ).return_value.chat.completions.create.return_value = provider
    response = post(tenant)
    next(iter(response.streaming_content))
    response.close()
    response.close()
    subscribtion.refresh_from_db()
    assert subscribtion.current_message_count == 1
    provider.close.assert_called_once()
    assert ChatMessage.objects.filter(sender="bot", message="Czynne 9-17.").exists()


@pytest.mark.django_db
def test_release_and_retry_does_not_charge_twice(tenant, subscribtion):
    ticket = reserve_message(tenant)
    ticket.charge()
    Reservation(ticket.row).charge()
    ticket.settle(False)
    subscribtion.refresh_from_db()
    assert subscribtion.current_message_count == 1
    ticket.row.refresh_from_db()
    assert ticket.row.state == "charged"
    assert ticket.row.finished


@pytest.mark.django_db
def test_late_reply_cannot_charge_new_cycle(tenant, subscribtion):
    ticket = reserve_message(tenant)
    old_cycle = subscribtion.billing_cycle_id
    subscribtion.reset_usage()
    assert subscribtion.billing_cycle_id != old_cycle
    ticket.charge()
    subscribtion.refresh_from_db()
    assert subscribtion.current_message_count == 0


@pytest.mark.django_db
def test_stale_middleware_reset_cannot_erase_new_usage(tenant, subscribtion):
    Subscription.objects.filter(pk=subscribtion.pk).update(
        billing_cycle_start=timezone.now().date() - timedelta(days=40)
    )
    first = Subscription.objects.get(pk=subscribtion.pk)
    second = Subscription.objects.get(pk=subscribtion.pk)
    first.reset_usage(only_if_due=True)
    reserve_message(tenant).charge()
    second.reset_usage(only_if_due=True)
    assert second.current_message_count == 1
    assert second.billing_cycle_id == first.billing_cycle_id


@pytest.mark.django_db
def test_dead_worker_holds_quota_until_reconciled(tenant, subscribtion):
    subscribtion.message_limit = 1
    subscribtion.save()
    ticket = reserve_message(tenant)
    MessageReservation.objects.filter(pk=ticket.row.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    with pytest.raises(ChatAdmissionDenied):
        reserve_message(tenant)
    ticket.row.refresh_from_db()
    assert ticket.row.state == "uncertain"
    ticket.charge()
    ticket.charge()
    subscribtion.refresh_from_db()
    assert subscribtion.current_message_count == 1


@pytest.mark.django_db
def test_concurrency_slot_is_held_after_first_token(tenant, subscribtion, settings):
    settings.CHAT_MAX_CONCURRENT = 1
    ticket = reserve_message(tenant)
    ticket.charge()
    with pytest.raises(ChatAdmissionDenied):
        reserve_message(tenant)
    ticket.settle(False)
    reserve_message(tenant).settle(False)


@pytest.mark.django_db
def test_free_test_budget_is_separate_and_counts_failures(tenant, subscribtion, settings):
    settings.CHAT_TEST_DAILY_LIMIT = 1
    ticket = reserve_message(tenant, is_test=True)
    ticket.settle(False)
    with pytest.raises(ChatAdmissionDenied):
        reserve_message(tenant, is_test=True)
    reserve_message(tenant).settle(False)
    subscribtion.refresh_from_db()
    assert subscribtion.current_message_count == 0


@pytest.mark.django_db
@pytest.mark.parametrize("invalid", ["zero", "inactive", "expired", "future"])
def test_admission_rechecks_subscription(tenant, subscribtion, invalid):
    if invalid == "zero":
        subscribtion.message_limit = 0
    elif invalid == "inactive":
        subscribtion.is_active = False
    elif invalid == "expired":
        subscribtion.end_date = timezone.now().date() - timedelta(days=1)
    else:
        subscribtion.start_date = timezone.now().date() + timedelta(days=1)
    subscribtion.save()
    with pytest.raises(ChatAdmissionDenied):
        reserve_message(tenant)
    assert not MessageReservation.objects.exists()


@pytest.mark.django_db
def test_rate_limit_survives_cache_reset(tenant, subscribtion, mocker):
    mocker.patch("accounts.message_quota.rate_for", return_value="1/min")
    reserve_message(tenant).settle(False)
    from django.core.cache import cache

    cache.clear()
    with pytest.raises(ChatAdmissionDenied):
        reserve_message(tenant)


@pytest.mark.django_db
def test_persistence_failure_does_not_refund_model_work(tenant, subscribtion, mocker):
    mocker.patch(
        "api.utils.chat_engine.get_openai_response", return_value={"content": "Witaj", "tokens": 1}
    )
    mocker.patch(
        "api.utils.chat_engine.persist_exchange", side_effect=RuntimeError("storage unavailable")
    )
    with pytest.raises(RuntimeError):
        post(tenant, "/api/widget/chat/")
    subscribtion.refresh_from_db()
    assert subscribtion.current_message_count == 1
    assert MessageReservation.objects.get().state == "charged"


@pytest.mark.django_db
def test_jwt_without_api_key_still_gets_tenant_throttle(tenant, user):
    from rest_framework.test import APIRequestFactory

    request = APIRequestFactory().post("/api/chat/test/")
    request.user = user
    request.tenant = tenant
    assert APIKeyRateThrottle().get_cache_key(request, None) == f"throttle_chat_tenant-{tenant.pk}"


@pytest.mark.django_db
def test_test_chat_validates_input_before_reserving(tenant, user, settings):
    from api.session_tokens import SessionRefreshToken as RefreshToken

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    result = client.post(
        "/api/chat/test/", {"message": "x" * (settings.MAX_WIADOMOSC_ZNAKOW + 1)}, format="json"
    )
    assert result.status_code == 400
    assert not MessageReservation.objects.exists()


@pytest.mark.django_db
def test_expired_unstarted_stream_cannot_reach_model(tenant, subscribtion, mocker):
    from accounts.message_quota import ReservedStream

    ticket = reserve_message(tenant)
    ticket.row.expires_at = timezone.now() - timedelta(seconds=1)
    calls = []

    def stream():
        calls.append("paid")
        yield "data"

    wrapped = ReservedStream(stream(), ticket)
    with pytest.raises(ChatAdmissionDenied):
        next(wrapped)
    assert calls == []
    ticket.row.refresh_from_db()
    assert ticket.row.state == "released"


@pytest.mark.django_db(transaction=True)
def test_concurrent_settlement_is_idempotent(tenant, subscribtion):
    ticket = reserve_message(tenant)

    def settle():
        close_old_connections()
        try:
            Reservation(ticket.row).charge()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: settle(), range(2)))
    subscribtion.refresh_from_db()
    assert subscribtion.current_message_count == 1


@pytest.mark.django_db
def test_tenant_budgets_are_independent(tenant, subscribtion, settings):
    from accounts.models import Tenant

    settings.CHAT_MAX_CONCURRENT = 1
    reserve_message(tenant)
    other = Tenant.objects.create(name="Other")
    reserve_message(other, is_test=True).settle(False)


@pytest.mark.django_db
def test_unknown_failure_keeps_quota_for_reconciliation(tenant, subscribtion):
    ticket = reserve_message(tenant)
    ticket.settle(None)
    ticket.row.refresh_from_db()
    assert ticket.row.state == "uncertain"
    assert ticket.row.finished
    subscribtion.refresh_from_db()
    assert subscribtion.current_message_count == 0


@pytest.mark.django_db
def test_check_and_reconcile_command(tenant, subscribtion):
    from io import StringIO

    from django.core.management import call_command
    from django.core.management.base import CommandError

    ticket = reserve_message(tenant)
    args = {"reservation": ticket.row.pk, "outcome": "charged", "stdout": StringIO()}
    with pytest.raises(CommandError, match="still be running"):
        call_command("check_message_reservations", **args)
    MessageReservation.objects.filter(pk=ticket.row.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    with pytest.raises(CommandError, match="need reconciliation"):
        call_command("check_message_reservations", stdout=StringIO())
    call_command("check_message_reservations", **args)
    call_command("check_message_reservations", **args)
    call_command("check_message_reservations", stdout=StringIO())
    subscribtion.refresh_from_db()
    assert subscribtion.current_message_count == 1
    with pytest.raises(CommandError, match="different terminal outcome"):
        call_command("check_message_reservations", reservation=ticket.row.pk, outcome="released")


@pytest.mark.django_db
def test_prune_keeps_uncertain_and_current_cycle(tenant, subscribtion):
    from io import StringIO

    from django.core.management import call_command

    old = timezone.now() - timedelta(days=91)
    settled = reserve_message(tenant)
    settled.charge()
    settled.settle(False)
    unresolved = reserve_message(tenant)
    unresolved.settle(None)
    MessageReservation.objects.update(created_at=old)
    call_command("check_message_reservations", prune=True, stdout=StringIO())
    assert MessageReservation.objects.count() == 2
    subscribtion.reset_usage()
    call_command("check_message_reservations", prune=True, stdout=StringIO())
    assert list(MessageReservation.objects.values_list("id", flat=True)) == [unresolved.row.pk]


@pytest.mark.django_db(transaction=True)
def test_stream_deadline_closes_provider_and_keeps_partial_reply(tenant, subscribtion, mocker):
    clock = mocker.patch("api.utils.chat_engine.time")
    clock.monotonic.side_effect = [0, 1, 100]
    provider = mocker.MagicMock()
    provider.__iter__.return_value = iter(
        [
            mocker.Mock(
                usage=None, choices=[mocker.Mock(delta=mocker.Mock(content="Czynne 9-17."))]
            ),
            mocker.Mock(usage=None, choices=[mocker.Mock(delta=mocker.Mock(content="Za późno"))]),
        ]
    )
    mocker.patch(
        "api.utils.chat_engine.get_client"
    ).return_value.chat.completions.create.return_value = provider
    response = post(tenant)
    try:
        content = b"".join(response.streaming_content).decode()
    finally:
        response.close()
    assert "Czynne 9-17." in content
    assert "Za późno" not in content
    provider.close.assert_called_once()
    subscribtion.refresh_from_db()
    assert subscribtion.current_message_count == 1


@pytest.mark.wolno_uzyc_klienta_openai
def test_openai_client_has_bounded_timeout_and_no_automatic_retries():
    from api.utils.chat_engine import get_client

    with get_client() as client:
        assert client.timeout == 60
        assert client.max_retries == 0


@pytest.mark.django_db
@pytest.mark.parametrize("queue_fails", [False, True])
def test_reserved_usage_alert_is_once_and_cannot_undo_charge(
    tenant, subscribtion, mocker, django_capture_on_commit_callbacks, queue_fails
):
    subscribtion.message_limit = 100
    subscribtion.current_message_count = 79
    subscribtion.save()
    enqueue = mocker.patch("documents.utils.queue.enqueue")
    if queue_fails:
        enqueue.side_effect = RuntimeError("queue unavailable")
    first, second = reserve_message(tenant), reserve_message(tenant)
    with django_capture_on_commit_callbacks(execute=True):
        first.charge()
        second.charge()
        first.charge()
    subscribtion.refresh_from_db()
    assert subscribtion.current_message_count == 81
    assert subscribtion.alert_threshold_sent == 80
    enqueue.assert_called_once()
