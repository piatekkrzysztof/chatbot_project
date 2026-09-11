from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Barrier

import pytest
from django.core import mail
from django.core.management import call_command
from django.db import close_old_connections, connections
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import CustomUser, DaneRozliczeniowe, PendingRegistration, Subscription, Tenant
from accounts.signup import digest
from api.tests.signup_helpers import latest_token
from api.tests.test_registration_security import PASSWORD, registration

START = "/api/accounts/register/"
ACTIVATE = "/api/accounts/registration/activate/"
PREVIEW = "/api/accounts/registration/preview/"
RESEND = "/api/accounts/registration/resend/"


def start(**changes):
    data = registration(**changes)
    data.pop("password", None)
    result = APIClient().post(START, data)
    assert result.status_code == 202, result.data
    return latest_token()


def activate(token, password=PASSWORD):
    return APIClient().post(ACTIVATE, {"token": token, "password": password})


@pytest.mark.django_db
def test_pending_registration_allocates_no_account_trial_or_stored_password():
    response = APIClient().post(START, registration())
    assert response.status_code == 202
    pending = PendingRegistration.objects.get()
    token = latest_token()
    assert pending.token_digest == digest(token)
    assert "password" not in pending.payload
    assert token not in str(response.data)
    assert token not in str(pending.__dict__)
    assert not CustomUser.objects.exists()
    assert not Tenant.objects.exists()
    assert not DaneRozliczeniowe.objects.exists()
    assert not Subscription.objects.exists()
    login = APIClient().post(
        "/api/accounts/login/",
        {
            "username": pending.email,
            "password": PASSWORD,
        },
    )
    assert login.status_code == 401


@pytest.mark.django_db
def test_mail_scanner_get_and_preview_never_activate():
    token = start()
    assert APIClient().get(ACTIVATE, {"token": token}).status_code == 405
    response = APIClient().post(PREVIEW, {"token": token})
    assert response.status_code == 200
    assert response.data == {"email": "new@example.com", "company_name": "Security test"}
    assert response["Cache-Control"] == "no-store"
    assert not Tenant.objects.exists()


@pytest.mark.django_db
def test_ownership_confirmation_creates_trial_once_and_uses_only_final_password():
    APIClient().post(START, registration(password=PASSWORD))
    token = latest_token()
    password = "  A-different!FinalSecret739  "
    assert activate(token, password).status_code == 201
    user = CustomUser.objects.get()
    assert user.check_password(password)
    assert not user.check_password(PASSWORD)
    assert Subscription.objects.get().start_date == timezone.now().date()
    assert activate(token).status_code == 400
    assert Tenant.objects.count() == 1
    assert PendingRegistration.objects.get().payload == {}
    login = APIClient().post(
        "/api/accounts/login/",
        {
            "username": user.email,
            "password": password,
        },
    )
    assert login.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("password", ["1", "1234567890", "password123", "AnnaNowak", "p" * 1025])
def test_bad_final_password_does_not_consume_link(password):
    token = start()
    assert activate(token, password).status_code == 400
    assert not Tenant.objects.exists()
    assert PendingRegistration.objects.get().used_at is None
    assert activate(token).status_code == 201


@pytest.mark.django_db
def test_expired_rotated_and_malformed_tokens_cannot_activate():
    token = start()
    PendingRegistration.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert activate(token).status_code == 400
    assert activate("invalid").status_code == 400
    assert activate("ż" * 43).status_code == 400
    assert not Tenant.objects.exists()


@pytest.mark.django_db
def test_resend_rotates_token_and_enforces_cooldown_per_address():
    token = start()
    assert APIClient().post(RESEND, {"email": "NEW@EXAMPLE.COM"}).status_code == 202
    assert len(mail.outbox) == 1
    PendingRegistration.objects.update(sent_at=timezone.now() - timedelta(minutes=2))
    assert APIClient().post(RESEND, {"email": "NEW@EXAMPLE.COM"}).status_code == 202
    new_token = latest_token()
    assert new_token != token
    assert activate(token).status_code == 400
    assert activate(new_token).status_code == 201


@pytest.mark.django_db
def test_resend_unknown_and_existing_account_have_identical_response(user):
    first = APIClient().post(RESEND, {"email": user.email})
    second = APIClient().post(RESEND, {"email": "unknown@example.com"})
    assert first.status_code == second.status_code == 202
    assert first.data == second.data
    assert not mail.outbox


@pytest.mark.django_db
def test_mail_failure_is_recoverable_without_partial_account(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr("accounts.signup.send_mail", lambda *a, **kw: 0)
        assert APIClient().post(START, registration()).status_code == 503
    assert PendingRegistration.objects.count() == 1
    assert not Tenant.objects.exists()
    PendingRegistration.objects.update(sent_at=timezone.now() - timedelta(minutes=2))
    assert APIClient().post(RESEND, {"email": "new@example.com"}).status_code == 202
    assert activate(latest_token()).status_code == 201


@pytest.mark.django_db
def test_trial_failure_rolls_back_account_and_preserves_link(monkeypatch):
    token = start()

    def fail(*args):
        raise RuntimeError("synthetic trial failure")

    with monkeypatch.context() as patch:
        patch.setattr("api.views.activation.zalozenie_okresu_probnego", fail)
        with pytest.raises(RuntimeError):
            activate(token)
    assert not Tenant.objects.exists()
    assert not CustomUser.objects.exists()
    assert not DaneRozliczeniowe.objects.exists()
    assert PendingRegistration.objects.get().used_at is None
    assert activate(token).status_code == 201


@pytest.mark.django_db
def test_paid_signup_does_not_call_stripe_or_start_trial():
    token = start(use_trial=False, plan="grow")
    response = activate(token)
    assert response.status_code == 201
    assert response.data["plan"] == "grow"
    assert response.data["use_trial"] is False
    assert not Subscription.objects.exists()
    assert "checkout_url" not in response.data


@pytest.mark.django_db
def test_email_claimed_between_start_and_activation_is_not_taken_over(tenant):
    token = start()
    owner = CustomUser.objects.create_user(
        username="existing",
        email="new@example.com",
        password=PASSWORD,
        tenant=tenant,
    )
    assert activate(token).status_code == 400
    assert CustomUser.objects.count() == 1
    owner.refresh_from_db()
    assert owner.tenant_id == tenant.pk


@pytest.mark.django_db(transaction=True)
def test_simultaneous_activation_creates_only_one_company(monkeypatch):
    token = start()
    barrier = Barrier(2)
    from api.views import activation

    original = activation.valid_pending

    def synchronized(*args, **kwargs):
        barrier.wait(timeout=10)
        return original(*args, **kwargs)

    monkeypatch.setattr(activation, "valid_pending", synchronized)

    def attempt(_):
        close_old_connections()
        try:
            return activate(token).status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == [201, 400]
    assert Tenant.objects.count() == CustomUser.objects.count() == Subscription.objects.count() == 1


@pytest.mark.django_db
def test_resend_daily_limit_survives_cache_reset():
    start()
    PendingRegistration.objects.update(
        send_count=5,
        sent_at=timezone.now() - timedelta(minutes=2),
    )
    assert APIClient().post(RESEND, {"email": "new@example.com"}).status_code == 202
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_pending_profile_cannot_be_replaced_by_unauthenticated_retry():
    start()
    APIClient().post(START, registration(company_name="Injected company"))
    assert PendingRegistration.objects.get().payload["company_name"] == "Security test"


@pytest.mark.django_db
def test_retention_removes_only_old_intents():
    start()
    PendingRegistration.objects.update(created_at=timezone.now() - timedelta(days=8))
    call_command("purge_pending_registrations", dry_run=True, stdout=StringIO())
    assert PendingRegistration.objects.count() == 1
    call_command("purge_pending_registrations", stdout=StringIO())
    assert not PendingRegistration.objects.exists()


@pytest.mark.django_db
def test_profile_correction_requires_a_new_token_after_cooldown():
    old_token = start()
    PendingRegistration.objects.update(sent_at=timezone.now() - timedelta(minutes=2))
    APIClient().post(START, registration(company_name="Corrected company"))
    new_token = latest_token()
    assert old_token != new_token
    assert activate(old_token).status_code == 400
    assert (
        APIClient().post(PREVIEW, {"token": new_token}).data["company_name"] == "Corrected company"
    )
    assert activate(new_token).status_code == 201
    assert Tenant.objects.get().name == "Corrected company"


@pytest.mark.django_db
def test_email_link_uses_configured_https_origin_not_host(settings):
    settings.DEBUG = False
    settings.FRONTEND_URL = "https://panel.example.com"
    APIClient().post(START, registration(), HTTP_HOST="testserver")
    assert "https://panel.example.com/potwierdz-email#token=" in mail.outbox[-1].body
    assert "testserver" not in mail.outbox[-1].body
