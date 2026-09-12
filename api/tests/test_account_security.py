import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest
from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections, connections
from django.utils import timezone
from rest_framework.test import APIClient

from accounts import dwuskladnikowe, totp
from accounts.models import CustomUser, DrugiSkladnik
from accounts.password_reset import reset_url
from accounts.sessions import LoginSession
from api.session_tokens import SessionRefreshToken
from api.tests.factories import UserFactory
from api.views import account_security

PANEL = "https://panel.example.test"
OLD = "testpass123"
NEW = "Independent-new-password!739"
BASE = "/api/accounts/"


def session(user):
    token = SessionRefreshToken.for_user(user)
    client = APIClient(HTTP_ORIGIN=PANEL, HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    return client, token


def change(client, **extra):
    return client.post(
        BASE + "password-change/",
        {"current_password": OLD, "new_password": NEW, **extra},
        format="json",
    )


def revoke(client, token, **extra):
    return client.post(
        BASE + f"sessions/{token['sid']}/revoke/", {"current_password": OLD, **extra}, format="json"
    )


def refresh(token):
    client = APIClient(HTTP_ORIGIN=PANEL)
    client.cookies[settings.NAZWA_CIASTECZKA_ODSWIEZANIA] = str(token)
    return client.post(BASE + "token/refresh/")


def factor(user):
    return DrugiSkladnik.objects.create(
        uzytkownik=user, sekret=totp.nowy_sekret(), potwierdzony_od=timezone.now()
    )


@pytest.mark.django_db
def test_list_exposes_only_own_active_sessions_without_credentials():
    user = UserFactory()
    client, token = session(user)
    _, other = session(user)
    for same_tenant in (True, False):
        foreign = UserFactory(tenant=user.tenant) if same_tenant else UserFactory()
        session(foreign)
    _, revoked = session(user)
    LoginSession.objects.filter(pk=revoked["sid"]).update(revoked_at=timezone.now())
    _, expired = session(user)
    LoginSession.objects.filter(pk=expired["sid"]).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    _, stale_password = session(user)
    LoginSession.objects.filter(pk=stale_password["sid"]).update(password_fingerprint="old")
    response = client.get(BASE + "sessions/")
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store" and response["Referrer-Policy"] == "no-referrer"
    assert response.data["count"] == 2
    assert response.data["mfa_enabled"] is False
    assert {row["id"] for row in response.data["results"]} == {token["sid"], other["sid"]}
    for row in response.data["results"]:
        assert set(row) == {"id", "created_at", "expires_at", "current"}
        assert row["current"] == (row["id"] == token["sid"])
    assert not response.cookies


@pytest.mark.django_db
def test_list_has_bounded_pagination_for_staff_too():
    user = UserFactory(is_staff=True, is_superuser=True)
    client, token = session(user)
    now = timezone.now()
    LoginSession.objects.bulk_create(
        [
            LoginSession(
                user=user,
                password_fingerprint=user.get_session_auth_hash(),
                expires_at=now + timedelta(days=1),
            )
            for _ in range(22)
        ]
    )
    session(UserFactory())
    first = client.get(BASE + "sessions/?page_size=99999")
    second = client.get(BASE + "sessions/?page=2")
    assert first.data["count"] == 23
    assert len(first.data["results"]) == 20
    assert len(second.data["results"]) == 3
    assert not (
        {x["id"] for x in first.data["results"]} & {x["id"] for x in second.data["results"]}
    )
    assert token["sid"] in {x["id"] for x in second.data["results"]}


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["sessions/", "password-change/", "sessions/revoke-others/"])
def test_public_widget_key_never_authenticates_security_settings(path):
    user = UserFactory()
    client = APIClient(HTTP_X_API_KEY=str(user.tenant.api_key), HTTP_ORIGIN=PANEL)
    response = client.get(BASE + path) if path == "sessions/" else client.post(BASE + path, {})
    assert response.status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["missing", "same_tenant", "other_tenant"])
def test_revocation_does_not_authorize_foreign_objects(kind):
    user = UserFactory(role="owner", is_staff=True, is_superuser=True)
    client, token = session(user)
    foreign = UserFactory(tenant=user.tenant) if kind == "same_tenant" else UserFactory()
    _, foreign_token = session(foreign)
    identity = uuid.uuid4() if kind == "missing" else foreign_token["sid"]
    response = client.post(BASE + f"sessions/{identity}/revoke/", {"current_password": OLD})
    assert response.status_code == 404
    assert response.data["detail"] == "Nie znaleziono sesji."
    assert refresh(token).status_code == refresh(foreign_token).status_code == 200


@pytest.mark.django_db
def test_revoke_other_and_repeat_leave_current_active_and_preserve_cookies():
    user = UserFactory()
    client, current = session(user)
    other_client, other = session(user)
    first = revoke(client, other)
    assert first.status_code == revoke(client, other).status_code == 200
    assert first.data["current_session_revoked"] is False
    assert not first.cookies
    assert other_client.get(BASE + "me/").status_code == 401
    assert refresh(other).status_code == 401
    assert refresh(current).status_code == 200


@pytest.mark.django_db
def test_revoke_others_excludes_current_and_other_users():
    user = UserFactory()
    client, current = session(user)
    _, other = session(user)
    foreign_client, foreign = session(UserFactory(tenant=user.tenant))
    response = client.post(BASE + "sessions/revoke-others/", {"current_password": OLD})
    assert response.status_code == 200 and response.data["current_session_revoked"] is False
    assert refresh(other).status_code == 401
    assert refresh(current).status_code == refresh(foreign).status_code == 200
    assert foreign_client.get(BASE + "sessions/").status_code == 200


@pytest.mark.django_db
def test_revoking_current_session_ends_its_access_and_refresh_without_cookie_mutation():
    client, current = session(UserFactory())
    response = revoke(client, current)
    assert response.status_code == 200 and response.data["current_session_revoked"] is True
    assert not response.cookies
    assert client.get(BASE + "me/").status_code == refresh(current).status_code == 401


@pytest.mark.django_db
def test_password_change_revokes_all_access_refresh_and_password_reset_links():
    user = UserFactory()
    client, first = session(user)
    second_client, second = session(user)
    data = {key: values[0] for key, values in parse_qs(urlsplit(reset_url(user)).fragment).items()}
    response = change(client)
    assert response.status_code == 200 and response.data["current_session_revoked"] is True
    assert not response.cookies and "access" not in response.data
    user.refresh_from_db()
    assert user.check_password(NEW)
    assert all(LoginSession.objects.filter(user=user).values_list("revoked_at", flat=True))
    for c, token in [(client, first), (second_client, second)]:
        assert c.get(BASE + "me/").status_code == refresh(token).status_code == 401
    assert (
        APIClient(HTTP_ORIGIN=PANEL).post(BASE + "password-reset/preview/", data).status_code == 400
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "bad", [{"current_password": "wrong"}, {"new_password": "123"}, {"new_password": OLD}]
)
def test_wrong_current_weak_and_unchanged_password_are_rejected_without_side_effects(bad):
    user = UserFactory()
    client, token = session(user)
    assert change(client, **bad).status_code == 400
    user.refresh_from_db()
    assert user.check_password(OLD)
    assert refresh(token).status_code == 200


@pytest.mark.django_db
def test_password_spaces_are_preserved():
    user = UserFactory()
    user.set_password("  " + OLD + "  ")
    user.save()
    client, _ = session(user)
    assert (
        change(
            client, current_password="  " + OLD + "  ", new_password="  " + NEW + "  "
        ).status_code
        == 200
    )
    user.refresh_from_db()
    assert user.check_password("  " + NEW + "  ")


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ["password", "others", "current"])
def test_mfa_is_required_and_stays_enabled(operation):
    user = UserFactory()
    f = factor(user)
    client, token = session(user)

    def perform(code):
        if operation == "password":
            return change(client, kod=code)
        if operation == "current":
            return revoke(client, token, kod=code)
        return client.post(BASE + "sessions/revoke-others/", {"current_password": OLD, "kod": code})

    assert perform("").status_code == 400
    assert perform(totp.kod(f.sekret)).status_code == 200
    f.refresh_from_db()
    assert f.wlaczony and f.ostatni_krok is not None
    if operation == "password":
        login = APIClient(HTTP_ORIGIN=PANEL).post(
            BASE + "login/", {"username": user.username, "password": NEW}
        )
        assert login.data["wymaga_drugiego_skladnika"] is True and "access" not in login.data


@pytest.mark.django_db
def test_weak_password_does_not_consume_backup_code_and_write_failure_rolls_it_back():
    user = UserFactory()
    factor(user)
    backup = dwuskladnikowe.wygeneruj_kody_zapasowe(user)[0]
    client, token = session(user)
    assert change(client, new_password="123", kod=backup).status_code == 400
    with patch.object(CustomUser, "save", side_effect=RuntimeError("synthetic")):
        with pytest.raises(RuntimeError):
            change(client, kod=backup)
    user.refresh_from_db()
    assert user.check_password(OLD)
    assert not LoginSession.objects.get(pk=token["sid"]).revoked_at
    assert change(client, kod=backup).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("invalidated", ["revoked", "password", "inactive", "deleted"])
def test_session_is_rechecked_after_authentication_under_lock(invalidated):
    user = UserFactory()
    client, token = session(user)
    original = account_security.locked_account

    def intervening(request, data):
        if invalidated == "revoked":
            LoginSession.objects.filter(pk=token["sid"]).update(revoked_at=timezone.now())
        elif invalidated == "password":
            CustomUser.objects.filter(pk=user.pk).update(password="unusable")
        elif invalidated == "inactive":
            CustomUser.objects.filter(pk=user.pk).update(is_active=False)
        else:
            CustomUser.objects.filter(pk=user.pk).delete()
        return original(request, data)

    with patch.object(account_security, "locked_account", side_effect=intervening):
        assert change(client).status_code == 401


@pytest.mark.django_db
def test_mutations_require_trusted_origin_and_fail_closed_on_cache_error():
    user = UserFactory()
    client, token = session(user)
    for suffix in (
        "password-change/",
        "sessions/revoke-others/",
        f"sessions/{token['sid']}/revoke/",
    ):
        response = client.post(
            BASE + suffix,
            {"current_password": OLD, "new_password": NEW},
            HTTP_ORIGIN="https://evil.example.test",
        )
        assert response.status_code == 403
    with patch.object(cache, "add", side_effect=RuntimeError("synthetic")):
        assert change(client).status_code == 503
    user.refresh_from_db()
    assert user.check_password(OLD)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("race", ["password", "reset", "refresh", "revoke"])
def test_parallel_security_mutations_cannot_leave_revoked_access_alive(race):
    user = UserFactory()
    client, token = session(user)
    reset_data = {
        key: values[0] for key, values in parse_qs(urlsplit(reset_url(user)).fragment).items()
    }
    gate = Barrier(2)

    def run(index):
        close_old_connections()
        try:
            gate.wait(timeout=10)
            c = APIClient(HTTP_ORIGIN=PANEL, HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
            if index == 0:
                result = revoke(c, token) if race == "revoke" else change(c)
            elif race in ("refresh", "revoke"):
                result = refresh(token)
            elif race == "reset":
                result = APIClient(HTTP_ORIGIN=PANEL).post(
                    BASE + "password-reset/confirm/", {**reset_data, "password": NEW + "reset"}
                )
            else:
                result = change(c)
            return result.status_code, result.data.get("access")
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(run, [0, 1]))
    assert 200 in [status for status, _ in result]
    assert all(status in (200, 400, 401) for status, _ in result)
    if race in ("password", "reset"):
        assert sum(status == 200 for status, _ in result) == 1
    assert client.get(BASE + "me/").status_code == 401
    assert refresh(token).status_code == 401
    for _, access in result:
        if access:
            assert (
                APIClient(HTTP_AUTHORIZATION=f"Bearer {access}").get(BASE + "me/").status_code
                == 401
            )
