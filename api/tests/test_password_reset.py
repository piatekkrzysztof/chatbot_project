from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.db import close_old_connections, connections
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import UntypedToken

from accounts import totp
from accounts.models import DrugiSkladnik
from accounts.password_reset import DeliveryUnavailable, deliver_reset, generator, reset_url
from accounts.tasks import send_password_reset
from api.session_tokens import SessionRefreshToken
from api.tests.factories import UserFactory
from chatbot_project.observability import redact_credentials


def test_email_daily_limit_is_enforced_without_plaintext_cache_keys():
    from api.password_throttles import allow_email

    counts = {}

    def add(key, value, timeout):
        assert "private@example.test" not in key
        if key.endswith(":minute"):
            return True  # A minute has elapsed between requests.
        if key in counts:
            return False
        counts[key] = value
        return True

    def incr(key):
        counts[key] += 1
        return counts[key]

    with patch.object(cache, "add", side_effect=add), patch.object(cache, "incr", side_effect=incr):
        assert [allow_email("private@example.test") for _ in range(7)] == [True] * 5 + [False] * 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    [
        "http://panel.example.test",
        "https://user:pass@example.test",
        "https://example.test?redirect=evil",
        "https://example.test#fragment",
    ],
)
def test_worker_refuses_unsafe_production_link_configuration(settings, url):
    settings.DEBUG = False
    settings.FRONTEND_URL = url
    user = UserFactory()
    with patch("accounts.password_reset.send_mail") as sender:
        with pytest.raises(DeliveryUnavailable):
            deliver_reset(user.email)
    sender.assert_not_called()


PASSWORD = "Independent-reset!739-new"
PANEL = "https://panel.example.test"


def proof(user):
    data = parse_qs(urlsplit(reset_url(user)).fragment)
    return {name: values[0] for name, values in data.items()}


def post(action, data):
    return APIClient(HTTP_ORIGIN=PANEL).post(
        f"/api/accounts/password-reset/{action}/", data, format="json"
    )


@pytest.mark.django_db
def test_request_enqueues_before_lookup_and_does_not_reveal_account(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = False
    user = UserFactory()
    with patch.object(send_password_reset, "apply_async") as queue:
        with patch("accounts.password_reset.CustomUser.objects.filter", side_effect=AssertionError):
            known = post("request", {"email": user.email.upper()})
            unknown = post("request", {"email": "unknown@example.test"})
    assert known.status_code == unknown.status_code == 202
    assert known.data == unknown.data
    assert known["Cache-Control"] == "no-store"
    assert known["Referrer-Policy"] == "no-referrer"
    assert queue.call_count == 2
    assert queue.call_args_list[0].kwargs["args"] == [user.email.lower()]
    assert queue.call_args.kwargs["argsrepr"] == "(<redacted>,)"
    assert queue.call_args.kwargs["expires"] == 300


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["unknown", "inactive", "unusable"])
def test_worker_does_not_mail_ineligible_accounts(kind):
    user = UserFactory()
    email = user.email
    if kind == "unknown":
        email = "absent@example.test"
    elif kind == "inactive":
        user.is_active = False
        user.save()
    else:
        user.set_unusable_password()
        user.save()
    with patch("accounts.password_reset.send_mail") as sender:
        send_password_reset.run(email)
    sender.assert_not_called()


@pytest.mark.django_db
def test_mail_contains_valid_fragment_link_without_changing_password():
    user = UserFactory()
    before = user.password
    deliver_reset(user.email)
    user.refresh_from_db()
    assert user.password == before
    message = mail.outbox[-1]
    url = next(line for line in message.body.splitlines() if line.startswith("https://"))
    assert urlsplit(url).netloc == "panel.example.test"
    assert not urlsplit(url).query
    data = {key: values[0] for key, values in parse_qs(urlsplit(url).fragment).items()}
    assert post("preview", data).status_code == 200
    assert post("preview", data).status_code == 200
    assert user.email not in post("preview", data).content.decode()
    assert PASSWORD not in message.body


@pytest.mark.django_db
def test_confirmation_revokes_all_sessions_keeps_mfa_and_does_not_login():
    user = UserFactory()
    tokens = [SessionRefreshToken.for_user(user) for _ in range(2)]
    factor = DrugiSkladnik.objects.create(
        uzytkownik=user, sekret=totp.nowy_sekret(), potwierdzony_od=timezone.now()
    )
    secret = factor.sekret
    data = proof(user)
    response = post("confirm", {**data, "password": PASSWORD})
    assert response.status_code == 200
    assert not response.cookies and "access" not in response.data
    user.refresh_from_db()
    factor.refresh_from_db()
    assert user.check_password(PASSWORD)
    assert factor.wlaczony and factor.sekret == secret
    for token in tokens:
        client = APIClient(HTTP_ORIGIN=PANEL)
        client.cookies[settings.NAZWA_CIASTECZKA_ODSWIEZANIA] = str(token)
        assert client.post("/api/accounts/token/refresh/").status_code == 401
        assert (
            client.get(
                "/api/accounts/me/", HTTP_AUTHORIZATION=f"Bearer {token.access_token}"
            ).status_code
            == 401
        )
    assert post("confirm", {**data, "password": PASSWORD}).status_code == 400
    login = APIClient(HTTP_ORIGIN=PANEL).post(
        "/api/accounts/login/", {"username": user.username, "password": PASSWORD}
    )
    assert login.data["wymaga_drugiego_skladnika"] is True
    assert "access" not in login.data


@pytest.mark.django_db
@pytest.mark.parametrize("change", ["password", "email", "inactive", "delete", "time", "tamper"])
def test_token_is_invalidated_by_account_changes_and_expiry(change):
    user = UserFactory()
    data = proof(user)
    if change == "password":
        user.set_password(PASSWORD)
        user.save()
    elif change == "email":
        user.email = "changed@example.test"
        user.save()
    elif change == "inactive":
        user.is_active = False
        user.save()
    elif change == "delete":
        user.delete()
    elif change == "tamper":
        data["token"] = data["token"][:-1] + ("1" if data["token"][-1] != "1" else "2")
    if change == "time":
        with patch.object(generator, "_now", return_value=generator._now() + timedelta(minutes=31)):
            response = post("confirm", {**data, "password": PASSWORD})
    else:
        response = post("confirm", {**data, "password": PASSWORD})
    assert response.status_code == 400


@pytest.mark.django_db
def test_weak_password_does_not_consume_link_and_spaces_are_preserved():
    user = UserFactory()
    data = proof(user)
    assert post("confirm", {**data, "password": "password"}).status_code == 400
    assert post("preview", data).status_code == 200
    spaced = f"  {PASSWORD}  "
    assert post("confirm", {**data, "password": spaced}).status_code == 200
    user.refresh_from_db()
    assert user.check_password(spaced) and not user.check_password(PASSWORD)


@pytest.mark.django_db(transaction=True)
def test_only_one_parallel_reset_succeeds():
    user = UserFactory()
    data = {**proof(user), "password": PASSWORD}
    gate = Barrier(2)

    def attempt(_):
        close_old_connections()
        try:
            gate.wait(timeout=10)
            return post("confirm", data).status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == [200, 400]


@pytest.mark.django_db
def test_failed_password_save_leaves_link_and_password_unchanged():
    user = UserFactory()
    data = proof(user)
    with patch.object(type(user), "save", side_effect=RuntimeError("synthetic")):
        with pytest.raises(RuntimeError):
            post("confirm", {**data, "password": PASSWORD})
    user.refresh_from_db()
    assert user.check_password("testpass123")
    assert post("preview", data).status_code == 200


@pytest.mark.django_db
def test_smtp_errors_are_sanitized_and_retried():
    user = UserFactory()
    with patch("accounts.password_reset.send_mail", side_effect=RuntimeError("sensitive SMTP")):
        with pytest.raises(DeliveryUnavailable, match="delivery unavailable") as error:
            deliver_reset(user.email)
        assert "sensitive" not in str(error.value)
        with patch.object(send_password_reset, "retry", side_effect=RuntimeError("retry")) as retry:
            with pytest.raises(RuntimeError, match="retry"):
                send_password_reset.run(user.email)
        assert retry.call_args.kwargs["countdown"] == 60


@pytest.mark.django_db
def test_broker_failure_and_eager_production_are_closed(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = False
    with patch.object(send_password_reset, "apply_async", side_effect=RuntimeError("secret")):
        response = post("request", {"email": "unknown@example.test"})
    assert response.status_code == 503 and "secret" not in response.content.decode()
    settings.DEBUG = False
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with patch.object(send_password_reset, "apply_async") as queue:
        assert post("request", {"email": "other@example.test"}).status_code == 503
    queue.assert_not_called()


@pytest.mark.django_db
def test_request_limits_known_and_unknown_emails_identically(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = False
    user = UserFactory()
    with patch.object(send_password_reset, "apply_async") as queue:
        for email in (user.email, "unknown@example.test"):
            for _ in range(2):
                assert post("request", {"email": email}).status_code == 202
    assert queue.call_count == 2


@pytest.mark.django_db
def test_cache_failure_is_closed():
    with patch.object(cache, "add", side_effect=RuntimeError("secret")):
        response = post("request", {"email": "unknown@example.test"})
    assert response.status_code == 503 and "secret" not in response.content.decode()


@pytest.mark.parametrize("action", ["request", "preview", "confirm"])
def test_untrusted_origin_cannot_start_recovery(action):
    response = APIClient(HTTP_ORIGIN="https://evil.example.test").post(
        f"/api/accounts/password-reset/{action}/", {}, format="json"
    )
    assert response.status_code == 403
    assert response["Cache-Control"] == "no-store"


@pytest.mark.django_db
@pytest.mark.parametrize("uid", ["!", "a" * 100, "OTIyMzM3MjAzNjg1NDc3NTgwOA", "AA"])
def test_invalid_uid_does_not_cause_server_error(uid):
    data = {**proof(UserFactory()), "uid": uid, "password": PASSWORD}
    assert post("confirm", data).status_code == 400


def test_error_reporting_removes_password_body_and_task_arguments():
    event = {
        "request": {"data": {"password": "synthetic"}, "cookies": "synthetic"},
        "extra": {"celery-job": {"task_name": "reset", "args": ["private"], "kwargs": {}}},
    }
    result = redact_credentials(event, {})
    assert result["request"] == {}
    assert result["extra"]["celery-job"] == {"task_name": "reset"}


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [{}, {"haslo": "wrong"}])
def test_stolen_session_cannot_create_or_replace_mfa_secret(payload):
    user = UserFactory()
    client = APIClient(HTTP_ORIGIN=PANEL)
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_API_KEY=str(user.tenant.api_key))
    assert client.post("/api/accounts/2fa/rozpocznij/", payload).status_code == 400
    assert not DrugiSkladnik.objects.filter(uzytkownik=user).exists()


@pytest.mark.django_db
def test_mfa_confirmation_requires_password_and_preserves_code_on_failure():
    user = UserFactory()
    client = APIClient(HTTP_ORIGIN=PANEL)
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_API_KEY=str(user.tenant.api_key))
    response = client.post("/api/accounts/2fa/rozpocznij/", {"haslo": "testpass123"})
    assert response.status_code == 201
    code = totp.kod(response.data["sekret"])
    for payload in ({"kod": code}, {"kod": code, "haslo": "wrong"}):
        assert client.post("/api/accounts/2fa/potwierdz/", payload).status_code == 400
    assert (
        client.post(
            "/api/accounts/2fa/potwierdz/", {"kod": code, "haslo": "testpass123"}
        ).status_code
        == 200
    )
