from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from django.conf import settings
from django.db import close_old_connections, connections
from rest_framework.test import APIClient

from api.session_tokens import SessionRefreshToken as RefreshToken
from api.tests.factories import UserFactory


def refresh(value):
    client = APIClient(HTTP_ORIGIN="https://panel.example.test")
    client.cookies[settings.NAZWA_CIASTECZKA_ODSWIEZANIA] = value
    return client.post("/api/accounts/token/refresh/")


@pytest.mark.django_db(transaction=True)
def test_only_one_concurrent_refresh_can_issue_tokens():
    user = UserFactory()
    value = str(RefreshToken.for_user(user))
    barrier = Barrier(2)

    def attempt(_):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return refresh(value)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(response.status_code for response in results) == [200, 409]
    loser = next(response for response in results if response.status_code == 409)
    assert not loser.cookies
    assert "access" not in loser.data
    winner = next(response for response in results if response.status_code == 200)
    assert refresh(winner.cookies[settings.NAZWA_CIASTECZKA_ODSWIEZANIA].value).status_code == 200


@pytest.mark.django_db
def test_replay_does_not_erase_the_current_browser_cookie():
    value = str(RefreshToken.for_user(UserFactory()))
    first = refresh(value)
    replay = refresh(value)
    assert replay.status_code == 409
    assert replay.data["code"] == "refresh_conflict"
    assert not replay.cookies
    assert replay["Cache-Control"] == "no-store"
    assert refresh(first.cookies[settings.NAZWA_CIASTECZKA_ODSWIEZANIA].value).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("change", ["delete", "deactivate"])
def test_unavailable_account_returns_401_instead_of_500(change):
    user = UserFactory()
    value = str(RefreshToken.for_user(user))
    if change == "delete":
        user.delete()
    else:
        user.is_active = False
        user.save(update_fields=["is_active"])
    response = refresh(value)
    assert response.status_code == 401
    assert "access" not in response.data


@pytest.mark.django_db
def test_failed_rotation_rolls_back_consumption():
    value = str(RefreshToken.for_user(UserFactory()))
    with patch.object(RefreshToken, "outstand", side_effect=RuntimeError("synthetic failure")):
        with pytest.raises(RuntimeError):
            refresh(value)
    assert refresh(value).status_code == 200


@pytest.mark.django_db
def test_access_token_cannot_be_used_as_refresh():
    token = RefreshToken.for_user(UserFactory())
    assert refresh(str(token.access_token)).status_code == 401
    assert refresh(str(token)).status_code == 200
