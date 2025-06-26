from datetime import timedelta
from django.utils import timezone

import pytest
from rest_framework.test import APIClient
from accounts.models import Tenant, CustomUser, InvitationToken
from uuid import UUID


@pytest.mark.django_db
def test_owner_can_create_invitation(user, tenant, subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.role = "owner"
    user.save()
    tenant.save()
    client.force_authenticate(user=user)

    response = client.post("/api/accounts/invitations/", {
        "email": "new@org.com",
        "role": "employee",

    }, HTTP_X_API_KEY=str(tenant.api_key))
    assert response.status_code == 201
    assert InvitationToken.objects.filter(email="new@org.com").exists()


@pytest.mark.django_db
def test_accept_invitation_creates_user(user, tenant, subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.role = "owner"
    user.save()
    tenant.save()
    client.force_authenticate(user=user)
    token = InvitationToken.objects.create(tenant=tenant, role="employee")

    client = APIClient()
    response = client.post("/api/accounts/accept-invite/", {
        "token": str(token.token),
        "username": "newuser",
        "email": "new@x.com",
        "password": "SafePass123",
    }
                           , HTTP_X_API_KEY=str(tenant.api_key))
    assert response.status_code == 201
    assert CustomUser.objects.filter(username="newuser").exists()
    token.refresh_from_db()
    assert token.users == 1


@pytest.mark.django_db
def test_accept_invitation_fails_with_expired_token(user, tenant, subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.role = "owner"
    user.save()
    tenant.save()
    client.force_authenticate(user=user)
    token = InvitationToken.objects.create(
        tenant=tenant,
        role="employee",
    )
    token.created_at = timezone.now() - timedelta(hours=2)
    token.save()

    client = APIClient()
    response = client.post("/api/accounts/accept-invite/", {
        "token": str(token.token),
        "username": "late",
        "email": "late@corp.com",
        "password": "Abc123456"
    }, HTTP_X_API_KEY=str(tenant.api_key))
    assert response.status_code == 400
    assert "Token expired" in str(response.data)


@pytest.mark.django_db
def test_accept_invitation_fails_with_fake_token(user, tenant, subscribtion):
    client = APIClient()
    response = client.post("/api/accounts/accept-invite/", {
        "token": "00000000-0000-0000-0000-000000000000",
        "username": "ghost",
        "email": "ghost@x.com",
        "password": "pass"
    })
    assert response.status_code == 400
