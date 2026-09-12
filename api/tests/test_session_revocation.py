"""Real HTTP checks, including revoked descendants and two database connections."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.conf import settings
from django.db import close_old_connections, connections
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken

from api.tests.factories import UserFactory

PANEL = "https://panel.example.test"


def login(user):
    client = APIClient(HTTP_ORIGIN=PANEL)
    response = client.post(
        "/api/accounts/login/", {"username": user.username, "password": "testpass123"}
    )
    assert response.status_code == 200
    return client, response.data["access"], cookie(client)


def cookie(client):
    return client.cookies[settings.NAZWA_CIASTECZKA_ODSWIEZANIA].value


def me(access):
    return APIClient().get("/api/accounts/me/", HTTP_AUTHORIZATION=f"Bearer {access}")


def use_refresh(value, path="token/refresh/"):
    client = APIClient(HTTP_ORIGIN=PANEL)
    client.cookies[settings.NAZWA_CIASTECZKA_ODSWIEZANIA] = value
    return client.post("/api/accounts/" + path)


@pytest.mark.django_db
def test_logout_revokes_access_and_all_rotated_descendants():
    client, access, ancestor = login(UserFactory())
    assert me(access).status_code == 200
    response = client.post("/api/accounts/token/refresh/")
    assert response.status_code == 200
    descendant, access2 = cookie(client), response.data["access"]
    # Stale cookie is still valid proof of which login should be revoked.
    assert use_refresh(ancestor, "logout/").status_code == 204
    assert me(access).status_code == 401
    assert me(access2).status_code == 401
    assert use_refresh(descendant).status_code == 401
    assert use_refresh(ancestor).status_code == 401
    assert use_refresh(ancestor, "logout/").status_code == 204


@pytest.mark.django_db
def test_logout_does_not_revoke_another_device_or_account():
    user = UserFactory()
    first, access1, _ = login(user)
    _, access2, refresh2 = login(user)
    _, access3, refresh3 = login(UserFactory())
    assert first.post("/api/accounts/logout/").status_code == 204
    assert me(access1).status_code == 401
    for access, refresh in ((access2, refresh2), (access3, refresh3)):
        assert me(access).status_code == 200
        assert use_refresh(refresh).status_code == 200


@pytest.mark.django_db
def test_password_change_revokes_every_session_without_using_signals():
    user = UserFactory()
    sessions = [login(user), login(user)]
    user.set_password("New-test-password-739!")
    type(user).objects.filter(pk=user.pk).update(password=user.password)
    for _, access, refresh in sessions:
        assert me(access).status_code == 401
        assert use_refresh(refresh).status_code == 401
    client = APIClient(HTTP_ORIGIN=PANEL)
    response = client.post(
        "/api/accounts/login/", {"username": user.username, "password": "New-test-password-739!"}
    )
    assert response.status_code == 200
    assert me(response.data["access"]).status_code == 200


@pytest.mark.django_db
def test_tokens_without_server_session_are_rejected():
    legacy = RefreshToken.for_user(UserFactory())
    assert me(str(legacy.access_token)).status_code == 401
    assert use_refresh(str(legacy)).status_code == 401


@pytest.mark.django_db
def test_rotation_preserves_session_and_absolute_expiry():
    client, access, value = login(UserFactory())
    original = UntypedToken(value)
    for _ in range(3):
        response = client.post("/api/accounts/token/refresh/")
        assert response.status_code == 200
        rotated = UntypedToken(cookie(client))
        assert rotated["sid"] == original["sid"]
        assert rotated["exp"] == original["exp"]
        assert UntypedToken(response.data["access"])["sid"] == original["sid"]
    assert me(access).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("sid", [None, "", "invalid", 123, [], {}])
def test_bad_session_claim_fails_closed(sid):
    _, access, value = login(UserFactory())
    token = UntypedToken(value)
    token["sid"] = sid
    assert use_refresh(str(token)).status_code == 401
    token = UntypedToken(access)
    token["sid"] = sid
    assert me(str(token)).status_code == 401


@pytest.mark.django_db
def test_session_cannot_be_borrowed_by_a_different_account():
    _, access, value = login(UserFactory())
    other = UserFactory()
    token = UntypedToken(value)
    token["user_id"] = str(other.pk)
    assert use_refresh(str(token)).status_code == 401
    assert use_refresh(str(token), "logout/").status_code == 204
    assert me(access).status_code == 200


@pytest.mark.django_db
def test_expired_or_removed_session_denies_unexpired_jwt():
    from django.utils import timezone

    from accounts.sessions import LoginSession

    _, access, value = login(UserFactory())
    session = LoginSession.objects.get(pk=UntypedToken(value)["sid"])
    session.expires_at = timezone.now() - timedelta(seconds=1)
    session.save(update_fields=["expires_at"])
    assert me(access).status_code == 401
    assert use_refresh(value).status_code == 401
    session.delete()
    assert me(access).status_code == 401
    assert use_refresh(value).status_code == 401


@pytest.mark.django_db(transaction=True)
def test_concurrent_refresh_and_logout_cannot_leave_a_live_descendant():
    _, access, value = login(UserFactory())
    gate = Barrier(2)

    def attempt(path):
        close_old_connections()
        try:
            gate.wait(timeout=10)
            return use_refresh(value, path)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        refresh, logout = list(pool.map(attempt, ("token/refresh/", "logout/")))
    assert logout.status_code == 204
    assert refresh.status_code in (200, 401)
    assert me(access).status_code == 401
    if refresh.status_code == 200:
        assert me(refresh.data["access"]).status_code == 401
        assert (
            use_refresh(refresh.cookies[settings.NAZWA_CIASTECZKA_ODSWIEZANIA].value).status_code
            == 401
        )


@pytest.mark.django_db
def test_failed_login_session_storage_rolls_back_token(monkeypatch):
    from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

    from accounts.sessions import LoginSession

    user = UserFactory()

    def fail(**kwargs):
        raise RuntimeError("synthetic session storage failure")

    monkeypatch.setattr(LoginSession.objects, "create", fail)
    with pytest.raises(RuntimeError, match="synthetic"):
        login(user)
    assert not OutstandingToken.objects.exists()
    assert not LoginSession.objects.exists()


@pytest.mark.django_db
def test_revoked_jwt_cannot_fall_back_to_widget_key():
    user = UserFactory()
    client, access, _ = login(user)
    client.post("/api/accounts/logout/")
    response = APIClient().get(
        "/api/widget-settings/",
        HTTP_AUTHORIZATION=f"Bearer {access}",
        HTTP_X_API_KEY=str(user.tenant.api_key),
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_drf_also_rejects_revoked_access_without_tenant_middleware():
    from rest_framework.test import APIRequestFactory

    from api.views.accounts import MeView

    user = UserFactory()
    client, access, _ = login(user)
    factory = APIRequestFactory()

    def request():
        result = factory.get("/", HTTP_AUTHORIZATION=f"Bearer {access}")
        # Supply only tenant context required by throttles, never an authenticated user.
        result.tenant = user.tenant
        return result

    assert MeView.as_view()(request()).status_code == 200
    client.post("/api/accounts/logout/")
    assert MeView.as_view()(request()).status_code == 401


@pytest.mark.django_db
def test_retention_removes_only_expired_sessions():
    from io import StringIO

    from django.core.management import call_command
    from django.utils import timezone

    from accounts.sessions import LoginSession

    client, access, _ = login(UserFactory())
    other, _, value = login(UserFactory())
    old_id = UntypedToken(value)["sid"]
    other.post("/api/accounts/logout/")
    LoginSession.objects.filter(pk=old_id).update(expires_at=timezone.now() - timedelta(days=2))
    call_command("purge_login_sessions", "--dry-run", stdout=StringIO())
    assert LoginSession.objects.count() == 2
    call_command("purge_login_sessions", stdout=StringIO())
    assert LoginSession.objects.count() == 1
    assert me(access).status_code == 200
    assert client.post("/api/accounts/token/refresh/").status_code == 200


def test_openapi_still_requires_bearer_authentication():
    from django.urls import path
    from drf_spectacular.generators import SchemaGenerator

    from api.views.accounts import MeView

    schema = SchemaGenerator(patterns=[path("me/", MeView.as_view())]).get_schema(public=True)
    assert schema["paths"]["/me/"]["get"]["security"] == [{"jwtAuth": []}]
    assert schema["components"]["securitySchemes"]["jwtAuth"]["scheme"] == "bearer"
