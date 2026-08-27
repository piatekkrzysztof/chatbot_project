"""
Pełna ścieżka zaproszenia pracownika: wysłanie, podgląd linku, założenie konta.

Ścieżka była zepsuta na dwóch poziomach naraz. TenantMiddleware przepuszczał bez
tenanta wyłącznie rejestrację i logowanie, więc zapraszany — który z definicji
nie ma jeszcze konta ani klucza API — dostawał 401 przy próbie przyjęcia
zaproszenia. Do tego nieudana wysyłka e-maila kończyła się pięćsetką mimo
poprawnie zapisanego tokenu, bo send_mail leciał z fail_silently=False.
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import CustomUser, InvitationDuration, InvitationToken


def owner_client(user, tenant):
    user.tenant = tenant
    user.role = "owner"
    user.save()
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_API_KEY=str(tenant.api_key))
    return client


@pytest.mark.django_db
def test_wlasciciel_dostaje_gotowy_link_do_skopiowania(user, tenant, mocker):
    mocker.patch("api.views.accounts.send_invitation_email")
    client = owner_client(user, tenant)

    response = client.post(
        "/api/accounts/invitations/",
        {"email": "pracownik@example.com", "role": "employee", "duration": "1d", "max_users": 1},
        format="json",
    )

    assert response.status_code == 201
    data = response.json()
    assert data["email_sent"] is True
    assert data["accept_url"].endswith(f"/invite/accept/{data['token']}")
    assert data["is_valid"] is True


@pytest.mark.django_db
def test_awaria_poczty_nie_przekresla_zaproszenia(user, tenant, mocker):
    """Token jest już zapisany, a link i tak widać w panelu — 500 byłoby kłamstwem."""
    mocker.patch(
        "api.views.accounts.send_invitation_email",
        side_effect=OSError("SMTP niedostępny"),
    )
    client = owner_client(user, tenant)

    response = client.post(
        "/api/accounts/invitations/",
        {"email": "pracownik@example.com", "role": "employee", "duration": "1d", "max_users": 1},
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["email_sent"] is False
    assert InvitationToken.objects.filter(email="pracownik@example.com").exists()


@pytest.mark.django_db
def test_zapraszany_widzi_podglad_bez_konta(tenant):
    """Anonimowy request bez klucza API — dokładnie ten, który blokował middleware."""
    invitation = InvitationToken.objects.create(
        tenant=tenant,
        email="nowy@example.com",
        role="employee",
        duration="1d",
        max_users=1,
    )

    response = APIClient().get(f"/api/accounts/invitations/{invitation.token}/preview/")

    assert response.status_code == 200
    data = response.json()
    assert data["company"] == tenant.name
    assert data["is_valid"] is True


@pytest.mark.django_db
def test_podglad_nieistniejacego_tokenu_daje_404(tenant):
    import uuid

    response = APIClient().get(f"/api/accounts/invitations/{uuid.uuid4()}/preview/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_zapraszany_zaklada_konto_bez_uwierzytelnienia(tenant):
    invitation = InvitationToken.objects.create(
        tenant=tenant,
        email="nowy@example.com",
        role="employee",
        duration="1d",
        max_users=1,
    )

    response = APIClient().post(
        "/api/accounts/accept-invite/",
        {
            "token": str(invitation.token),
            "username": "nowy",
            "email": "nowy@example.com",
            "password": "TajneHaslo123",
        },
        format="json",
    )

    assert response.status_code == 201
    nowy = CustomUser.objects.get(username="nowy")
    assert nowy.tenant == tenant
    assert nowy.role == "employee"


@pytest.mark.django_db
def test_zuzyte_zaproszenie_nie_dziala_drugi_raz(tenant):
    invitation = InvitationToken.objects.create(
        tenant=tenant,
        email="nowy@example.com",
        role="employee",
        duration="1d",
        max_users=1,
    )
    client = APIClient()
    payload = {
        "token": str(invitation.token),
        "email": "nowy@example.com",
        "password": "TajneHaslo123",
    }

    first = client.post(
        "/api/accounts/accept-invite/", {**payload, "username": "pierwszy"}, format="json"
    )
    second = client.post(
        "/api/accounts/accept-invite/", {**payload, "username": "drugi"}, format="json"
    )

    assert first.status_code == 201
    assert second.status_code == 400
    assert not CustomUser.objects.filter(username="drugi").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("duration", [d.value for d in InvitationDuration])
def test_kazdy_okres_waznosci_da_sie_wybrac(user, tenant, mocker, duration):
    """
    Panel wystawia listę okresów do wyboru, więc każda wartość ze słownika musi
    przejść przez serializer. Rozjazd między nimi objawia się dopiero w formularzu
    ("1w" nie jest poprawnym wyborem), bo testy zwykle sprawdzają jedną wartość.
    """
    mocker.patch("api.views.accounts.send_invitation_email")
    client = owner_client(user, tenant)

    response = client.post(
        "/api/accounts/invitations/",
        {"email": "kto@example.com", "role": "employee", "duration": duration, "max_users": 1},
        format="json",
    )

    assert response.status_code == 201, response.json()
    assert response.json()["expires_at"] is not None


def test_kazdy_okres_ma_zdefiniowany_czas_wygasniecia():
    """
    Brak wpisu w DURATION_DELTAS nie wywala się — po cichu skraca ważność do
    jednego dnia, więc "7 dni" wybrane w panelu przestawałoby działać po dobie.
    """
    brakujace = [
        d.value for d in InvitationDuration if d.value not in InvitationToken.DURATION_DELTAS
    ]

    assert brakujace == []


@pytest.mark.django_db
def test_wlasciciel_cofa_zaproszenie(user, tenant):
    invitation = InvitationToken.objects.create(
        tenant=tenant,
        email="pomylka@example.com",
        role="employee",
        duration="1d",
        max_users=1,
    )
    client = owner_client(user, tenant)

    response = client.delete(f"/api/accounts/invitations/{invitation.id}/")

    assert response.status_code == 204
    assert not InvitationToken.objects.filter(pk=invitation.pk).exists()


@pytest.mark.django_db
def test_nie_mozna_cofnac_cudzego_zaproszenia(user, tenant):
    from .factories import TenantFactory

    obcy = TenantFactory()
    cudze = InvitationToken.objects.create(
        tenant=obcy,
        email="ktos@example.com",
        role="employee",
        duration="1d",
        max_users=1,
    )
    client = owner_client(user, tenant)

    response = client.delete(f"/api/accounts/invitations/{cudze.id}/")

    assert response.status_code == 404
    assert InvitationToken.objects.filter(pk=cudze.pk).exists()


@pytest.mark.django_db
def test_lista_zaproszen_pokazuje_tylko_wlasne(user, tenant):
    from .factories import TenantFactory

    obcy = TenantFactory()
    InvitationToken.objects.create(
        tenant=tenant,
        email="moj@example.com",
        role="employee",
        duration="1d",
        max_users=1,
    )
    InvitationToken.objects.create(
        tenant=obcy,
        email="cudzy@example.com",
        role="employee",
        duration="1d",
        max_users=1,
    )

    client = owner_client(user, tenant)
    response = client.get("/api/accounts/invitations/list/")

    assert response.status_code == 200
    data = response.json()
    rows = data if isinstance(data, list) else data["results"]
    assert [row["email"] for row in rows] == ["moj@example.com"]
