"""Real HTTP session boundaries, including same-site sibling subdomains."""

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from api.session_tokens import SessionRefreshToken as RefreshToken
from api.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
PANEL = "https://panel.example.test"
ENDPOINTS = ("login/", "login/2fa/", "token/refresh/", "logout/")


@pytest.fixture
def session_client(settings):
    settings.FRONTEND_URL = PANEL
    settings.CSRF_TRUSTED_ORIGINS = [PANEL]
    settings.CIASTECZKO_ODSWIEZANIA_DOMENA = ".example.test"
    return APIClient(HTTP_ORIGIN=PANEL)


def login(client, user):
    return client.post(
        "/api/accounts/login/",
        {"username": user.username, "password": "testpass123"},
        format="json",
    )


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"HTTP_ORIGIN": "null", "HTTP_REFERER": PANEL + "/login"},
        {"HTTP_ORIGIN": "https://evil.example.test"},
        {"HTTP_ORIGIN": PANEL + ".evil.test"},
        {"HTTP_ORIGIN": PANEL + "/login"},
        {"HTTP_ORIGIN": "http://panel.example.test"},
        {"HTTP_ORIGIN": PANEL + ":444"},
        {"HTTP_ORIGIN": PANEL + ":0"},
        {"HTTP_ORIGIN": "\u0000" + PANEL},
        {"HTTP_ORIGIN": "https://attacker@panel.example.test"},
        {"HTTP_ORIGIN": "https://panel.example.test:bad"},
        {"HTTP_ORIGIN": PANEL + " https://evil.test"},
        {"HTTP_ORIGIN": "", "HTTP_REFERER": PANEL + "/login"},
        {"HTTP_REFERER": "https://evil.example.test/"},
        {"HTTP_SEC_FETCH_SITE": "same-site"},
    ],
)
def test_untrusted_request_cannot_mutate_session(session_client, endpoint, headers):
    user = UserFactory()
    refresh = RefreshToken.for_user(user)
    client = APIClient(**headers)
    client.cookies[settings.NAZWA_CIASTECZKA_ODSWIEZANIA] = str(refresh)
    response = client.post("/api/accounts/" + endpoint, {}, format="json")
    assert response.status_code == 403
    assert response["Cache-Control"] == "no-store"
    assert not response.cookies
    # A rejected refresh/logout must not consume the legitimate session.
    RefreshToken(str(refresh))


@pytest.mark.parametrize("endpoint", ("login/", "login/2fa/"))
def test_login_csrf_blocked_before_any_cookie_exists(session_client, endpoint):
    user = UserFactory()
    response = APIClient(HTTP_ORIGIN="https://evil.test").post(
        "/api/accounts/" + endpoint,
        {"username": user.username, "password": "testpass123"},
    )
    assert response.status_code == 403
    assert not response.cookies


@pytest.mark.parametrize("use_referer", [False, True])
def test_panel_can_login_rotate_and_logout(session_client, use_referer):
    if use_referer:
        session_client.defaults = {"HTTP_REFERER": PANEL + "/login?next=/dashboard"}
    user = UserFactory()
    response = login(session_client, user)
    assert response.status_code == 200
    assert "refresh" not in response.data
    cookie = response.cookies[settings.NAZWA_CIASTECZKA_ODSWIEZANIA]
    assert cookie["domain"] == ""
    assert cookie["httponly"]
    assert response.cookies[settings.NAZWA_CIASTECZKA_SESJI]["domain"] == ".example.test"
    response = session_client.post("/api/accounts/token/refresh/")
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert response.cookies[settings.NAZWA_CIASTECZKA_ODSWIEZANIA].value != cookie.value
    session_client.credentials(HTTP_AUTHORIZATION="Bearer expired-invalid-token")
    response = session_client.post("/api/accounts/logout/")
    assert response.status_code == 204
    assert response.cookies[settings.NAZWA_CIASTECZKA_ODSWIEZANIA]["max-age"] == 0


def test_legacy_cookie_and_body_token_cannot_restore_session(session_client):
    token = str(RefreshToken.for_user(UserFactory()))
    session_client.cookies["refresh_token"] = token
    response = session_client.post(
        "/api/accounts/token/refresh/", {"refresh": token}, format="json"
    )
    assert response.status_code == 401
    assert response.cookies["refresh_token"]["max-age"] == 0
    assert "access" not in response.data


def test_cors_widget_origin_does_not_grant_session_access(session_client, settings):
    settings.CORS_ALLOW_ALL_ORIGINS = True
    settings.CORS_ALLOWED_ORIGINS = ["https://evil.example.test"]
    response = APIClient(HTTP_ORIGIN="https://evil.example.test").post("/api/accounts/logout/")
    assert response.status_code == 403


def test_invalid_refresh_is_not_cacheable(session_client):
    session_client.cookies[settings.NAZWA_CIASTECZKA_ODSWIEZANIA] = "invalid"
    response = session_client.post("/api/accounts/token/refresh/")
    assert response.status_code == 401
    assert response["Cache-Control"] == "no-store"


def test_preflight_does_not_require_origin(session_client):
    response = APIClient().options("/api/accounts/token/refresh/")
    assert response.status_code == 200
