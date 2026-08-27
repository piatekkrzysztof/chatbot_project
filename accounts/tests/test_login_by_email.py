"""
Logowanie adresem e-mail.

Formularz logowania jest opisany "E-mail", ale Django uwierzytelnia po username.
Dotąd nikt tego nie zauważył, bo konta zakładane ręcznie miały username równy
adresowi. Pracownik przyjmujący zaproszenie wybiera własną nazwę użytkownika,
więc jego adres przestaje pasować — i osoba właśnie dodana do zespołu nie mogła
zalogować się tym, o co prosi ją formularz.
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import CustomUser


@pytest.fixture
def pracownik(tenant):
    return CustomUser.objects.create_user(
        username="nowypracownik",
        email="pracownik@example.com",
        password="TajneHaslo123",
        tenant=tenant,
        role="employee",
    )


@pytest.mark.django_db
def test_logowanie_adresem_email_gdy_username_jest_inny(pracownik):
    response = APIClient().post(
        "/api/accounts/login/",
        {"username": "pracownik@example.com", "password": "TajneHaslo123"},
        format="json",
    )

    assert response.status_code == 200
    assert "access" in response.json()


@pytest.mark.django_db
def test_logowanie_nazwa_uzytkownika_nadal_dziala(pracownik):
    """Konta założone wcześniej logują się nazwą — nie wolno tego zepsuć."""
    response = APIClient().post(
        "/api/accounts/login/",
        {"username": "nowypracownik", "password": "TajneHaslo123"},
        format="json",
    )

    assert response.status_code == 200


@pytest.mark.django_db
def test_zle_haslo_nie_wpuszcza(pracownik):
    response = APIClient().post(
        "/api/accounts/login/",
        {"username": "pracownik@example.com", "password": "zle-haslo"},
        format="json",
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_adres_uzywany_przez_kilka_kont_nie_wpuszcza(tenant, pracownik):
    """
    Ten sam adres w dwóch kontach nie wskazuje jednoznacznie użytkownika —
    zgadywanie oznaczałoby logowanie do cudzego konta.
    """
    CustomUser.objects.create_user(
        username="drugi",
        email="pracownik@example.com",
        password="TajneHaslo123",
        tenant=tenant,
        role="employee",
    )

    response = APIClient().post(
        "/api/accounts/login/",
        {"username": "pracownik@example.com", "password": "TajneHaslo123"},
        format="json",
    )

    assert response.status_code == 401
