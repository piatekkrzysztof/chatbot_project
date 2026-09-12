import io
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

import pytest
from billiard.exceptions import SoftTimeLimitExceeded
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connections, transaction
from django.utils import timezone

from accounts import security_notifications as notices
from accounts import totp
from accounts.models import CustomUser
from accounts.password_reset import confirm_reset
from accounts.tasks import send_password_notifications
from api.tests.factories import UserFactory
from api.tests.test_account_security import NEW, OLD, change, factor, session
from api.tests.test_password_reset import proof
from chatbot_project.celery import app


@pytest.fixture
def event(db):
    return notices.PasswordNotification.objects.create(
        user=UserFactory(), recipient="old@example.test"
    )


@pytest.mark.django_db
@pytest.mark.parametrize("flow", ["settings", "reset"])
def test_password_and_receipt_are_atomic_without_smtp_or_broker(flow):
    user = UserFactory()
    client, token = session(user)
    with patch.object(notices, "deliver", side_effect=AssertionError("No SMTP in request")):
        with patch.object(send_password_notifications, "apply_async", side_effect=AssertionError):
            if flow == "settings":
                assert change(client).status_code == 200
            else:
                confirm_reset(**proof(user), password=NEW)
    row = notices.PasswordNotification.objects.get()
    assert row.user_id == user.pk and row.recipient == user.email
    assert row.status == "pending" and row.attempts == 0
    assert NEW not in str(row.__dict__) and token["sid"] not in str(row.__dict__)
    assert not getattr(mail, "outbox", [])
    assert client.get("/api/accounts/me/").status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize("flow", ["settings", "reset"])
def test_outbox_failure_rolls_back_password_and_sessions(flow):
    user = UserFactory()
    client, _ = session(user)
    data = proof(user)
    with patch.object(notices.PasswordNotification.objects, "create", side_effect=RuntimeError):
        with pytest.raises(RuntimeError):
            if flow == "settings":
                change(client)
            else:
                confirm_reset(**data, password=NEW)
    user.refresh_from_db()
    assert user.check_password(OLD)
    assert client.get("/api/accounts/me/").status_code == 200
    assert not notices.PasswordNotification.objects.exists()
    confirm_reset(**data, password=NEW)
    assert notices.PasswordNotification.objects.count() == 1


@pytest.mark.django_db
def test_failed_validation_mfa_and_session_revocation_do_not_notify():
    user = UserFactory()
    client, _ = session(user)
    assert change(client, current_password="wrong").status_code == 400
    assert change(client, new_password="x").status_code == 400
    factor(user)
    assert change(client).status_code == 400
    assert not notices.PasswordNotification.objects.exists()
    other, _ = session(UserFactory())
    assert (
        other.post("/api/accounts/sessions/revoke-others/", {"current_password": OLD}).status_code
        == 200
    )
    assert not notices.PasswordNotification.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_outer_transaction_rollback_removes_event():
    user = UserFactory()
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            confirm_reset(**proof(user), password=NEW)
            assert notices.PasswordNotification.objects.count() == 1
            raise RuntimeError("Later write failed")
    user.refresh_from_db()
    assert user.check_password(OLD)
    assert not notices.PasswordNotification.objects.exists()
    with pytest.raises(RuntimeError, match="requires"):
        notices.record_password_change(user)


@pytest.mark.django_db
def test_outbox_failure_rolls_back_mfa_code_consumption():
    user = UserFactory()
    client, _ = session(user)
    mfa = factor(user)
    code = totp.kod(mfa.sekret)
    with patch.object(notices.PasswordNotification.objects, "create", side_effect=RuntimeError):
        with pytest.raises(RuntimeError):
            change(client, kod=code)
    assert change(client, kod=code).status_code == 200
    assert notices.PasswordNotification.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_worker_cannot_see_event_before_password_transaction_commits():
    user = UserFactory()

    def worker():
        close_old_connections()
        try:
            return notices.process_batch()
        finally:
            connections.close_all()

    with transaction.atomic():
        confirm_reset(**proof(user), password=NEW)
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(worker).result(timeout=10) == 0
    assert notices.process_batch() == 1


def test_smtp_delivery_holds_no_database_transaction():
    with patch.object(notices, "get_connection") as connection:
        with patch.object(notices, "EmailMessage") as message:
            message.return_value.send.return_value = 1
            event = notices.PasswordNotification(recipient="test@example.test")
            notices.deliver(event)
    connection.assert_called_once_with(timeout=15)


def test_delivery_uses_original_recipient_no_secret_and_skips_already_sent(event):
    CustomUser.objects.filter(pk=event.user_id).update(email="changed@example.test")
    assert send_password_notifications.run() == 1
    event.refresh_from_db()
    assert event.status == "sent" and event.sent_at and event.attempts == 1 and event.claim is None
    message = mail.outbox[-1]
    assert message.to == ["old@example.test"]
    assert "https://panel.example.test/odzyskaj-haslo" in message.body
    assert OLD not in message.body and "token=" not in message.body
    assert "MFA" in message.body and "Czas zmiany" in message.body
    assert send_password_notifications.run() == 0
    assert len(mail.outbox) == 1


@pytest.mark.parametrize("failure", ["smtp", "zero"])
def test_delivery_failure_sanitized_retry_then_success(event, caplog, failure):
    sender = patch.object(
        notices.EmailMessage,
        "send",
        **(
            {"side_effect": RuntimeError("SMTP secret@example.test private-password")}
            if failure == "smtp"
            else {"return_value": 0}
        ),
    )
    with sender:
        assert notices.process_batch() == 1
    event.refresh_from_db()
    assert event.status == "pending" and event.attempts == 1
    assert event.available_at > timezone.now() and event.sent_at is None
    assert event.last_error == "delivery_unavailable"
    assert "private-password" not in caplog.text and "secret@example.test" not in caplog.text
    assert notices.process_batch() == 0
    notices.PasswordNotification.objects.filter(pk=event.pk).update(available_at=timezone.now())
    notices.process_batch()
    event.refresh_from_db()
    assert event.status == "sent" and event.attempts == 2 and not event.last_error


def test_five_failed_attempts_are_terminal_and_do_not_block_next_message(event):
    with patch.object(notices, "deliver", side_effect=RuntimeError):
        for attempt in range(1, 6):
            notices.PasswordNotification.objects.filter(pk=event.pk).update(
                available_at=timezone.now()
            )
            assert notices.process_batch() == 1
            event.refresh_from_db()
            assert event.attempts == attempt
    assert event.status == "failed"
    notices.PasswordNotification.objects.create(user=event.user, recipient="next@example.test")
    assert notices.process_batch() == 1
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["next@example.test"]


def test_crashed_worker_is_reclaimed_only_after_lease(event):
    first = notices.claim_next()
    assert notices.claim_next() is None
    notices.PasswordNotification.objects.filter(pk=event.pk).update(available_at=timezone.now())
    second = notices.claim_next()
    assert second.claim != first.claim and second.attempts == 2
    assert (
        notices.PasswordNotification.objects.filter(pk=first.pk, claim=first.claim).update(
            status="sent"
        )
        == 0
    )


def test_crash_on_last_attempt_becomes_failed_without_another_email(event):
    notices.PasswordNotification.objects.filter(pk=event.pk).update(attempts=5, status="sending")
    with patch.object(notices, "deliver") as deliver:
        assert notices.process_batch() == 1
    deliver.assert_not_called()
    event.refresh_from_db()
    assert event.status == "failed" and event.last_error == "attempts_exhausted"


def test_soft_timeout_leaves_claim_for_restart_recovery(event):
    with patch.object(notices, "deliver", side_effect=SoftTimeLimitExceeded):
        with pytest.raises(SoftTimeLimitExceeded):
            notices.process_batch()
    event.refresh_from_db()
    assert event.status == "sending" and event.attempts == 1


def test_lost_database_ack_after_smtp_is_retried_with_same_message_id(event):
    with patch("django.db.models.query.QuerySet.update", side_effect=RuntimeError):
        with pytest.raises(RuntimeError):
            notices.process_batch()
    event.refresh_from_db()
    assert event.status == "sending" and len(mail.outbox) == 1
    notices.PasswordNotification.objects.filter(pk=event.pk).update(available_at=timezone.now())
    notices.process_batch()
    assert len(mail.outbox) == 2  # SMTP cannot guarantee exactly once after a lost ACK.
    assert mail.outbox[0].extra_headers == mail.outbox[1].extra_headers


@pytest.mark.django_db(transaction=True)
def test_parallel_workers_do_not_send_one_event_twice():
    event = notices.PasswordNotification.objects.create(
        user=UserFactory(), recipient="one@example.test"
    )
    barrier = Barrier(2)

    def run(_):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return notices.process_batch()
        finally:
            connections.close_all()

    with patch.object(notices, "deliver") as deliver:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sum(pool.map(run, range(2))) == 1
    deliver.assert_called_once()
    event.refresh_from_db()
    assert event.status == "sent" and event.attempts == 1


def test_one_batch_is_bounded(event):
    notices.PasswordNotification.objects.bulk_create(
        [
            notices.PasswordNotification(user=event.user, recipient="test@example.test")
            for _ in range(14)
        ]
    )
    with patch.object(notices, "deliver"):
        assert notices.process_batch() == 10
    assert notices.PasswordNotification.objects.filter(status="pending").count() == 5


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test",
        "https://x:y@example.test",
        "https://example.test?q=1",
        "https://example.test#x",
    ],
)
def test_unsafe_panel_configuration_fails_without_delivery(event, settings, url):
    settings.DEBUG = False
    settings.FRONTEND_URL = url
    notices.process_batch()
    assert not getattr(mail, "outbox", [])
    event.refresh_from_db()
    assert event.status == "pending" and event.last_error == "delivery_unavailable"


def test_deleting_user_removes_queued_pii(event):
    event.user.delete()
    assert not notices.PasswordNotification.objects.exists()
    assert notices.process_batch() == 0


def test_queue_checker_is_read_only_and_contains_no_recipients(event):
    output = io.StringIO()
    call_command("check_password_notifications", stdout=output)
    assert '"pending": 1' in output.getvalue()
    notices.PasswordNotification.objects.filter(pk=event.pk).update(
        created_at=timezone.now() - timedelta(minutes=11)
    )
    with pytest.raises(CommandError):
        call_command("check_password_notifications", stdout=output)
    assert event.recipient not in output.getvalue()
    event.refresh_from_db()
    assert event.status == "pending" and event.attempts == 0
    notices.PasswordNotification.objects.filter(pk=event.pk).update(
        status="failed", created_at=timezone.now()
    )
    with pytest.raises(CommandError):
        call_command("check_password_notifications", stdout=output)


def test_existing_worker_schedule_and_time_bounds():
    entry = app.conf.beat_schedule["password-notifications-every-minute"]
    assert entry["task"] == send_password_notifications.name
    assert entry["schedule"] == entry["options"]["expires"] == 60
    assert send_password_notifications.time_limit < notices.LEASE.total_seconds()
    assert send_password_notifications.soft_time_limit < send_password_notifications.time_limit
