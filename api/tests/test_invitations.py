import pytest
from rest_framework.test import APIClient
from accounts.models import Tenant, CustomUser, InvitationToken
from uuid import UUID

@pytest.mark.django_db
def test_owner_can_create_invitation():
    tenant = Tenant.objects.create(name="Org", owner_email="admin@org.com")
    owner = CustomUser.objects.create_user(username="a", password="b", tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=owner)

    response = client.post("/api/accounts/invitations/", {
        "email": "new@org.com",
        "role": "employee",
        "duration_hours": 24,
        "max_uses": 1
    })
    assert response.status_code == 201
    assert InvitationToken.objects.filter(email="new@org.com").exists()

@pytest.mark.django_db
def test_accept_invitation_creates_user():
    tenant = Tenant.objects.create(name="X", owner_email="admin@x.com")
    token = InvitationToken.objects.create(tenant=tenant, role="employee", duration_hours=24)

    client = APIClient()
    response = client.post("/api/accounts/accept-invite/", {
        "token": str(token.token),
        "username": "newuser",
        "email": "new@x.com",
        "password": "SafePass123"
    })
    assert response.status_code == 201
    assert CustomUser.objects.filter(username="newuser").exists()
    token.refresh_from_db()
    assert token.uses == 1