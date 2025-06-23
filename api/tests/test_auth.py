import pytest
from rest_framework.test import APIClient
from accounts.models import CustomUser, Tenant


@pytest.mark.django_db
def test_register_creates_user_and_tenant():
    client = APIClient()
    payload = {
        "company_name": "Acme Inc.",
        "email": "admin@acme.com",
        "password": "SuperHaslo123"
    }
    response = client.post("/api/accounts/register/", payload)
    assert response.status_code == 201
    assert CustomUser.objects.filter(email="admin@acme.com").exists()
    assert Tenant.objects.filter(name="Acme Inc.").exists()


@pytest.mark.django_db
def test_login_returns_token_and_user_data():
    tenant = Tenant.objects.create(name="Org", owner_email="x@x.com")
    user = CustomUser.objects.create_user(username="x", email="x@x.com", password="pass123", tenant=tenant)

    client = APIClient()
    response = client.post("/api/accounts/login/", {"username": "x", "password": "pass123"})
    assert response.status_code == 200
    assert "access" in response.data
    assert response.data["user"]["tenant_name"] == "Org"


@pytest.mark.django_db
def test_me_view_returns_logged_in_user():
    tenant = Tenant.objects.create(name="TestCo", owner_email="user@t.com")
    user = CustomUser.objects.create_user(username="u", email="user@t.com", password="pass", tenant=tenant)

    client = APIClient()
    client.force_authenticate(user=user, )

    response = client.get("/api/accounts/me/",HTTP_X_API_KEY=str(tenant.api_key))
    assert response.status_code == 200
    assert response.data["email"] == "user@t.com"

@pytest.mark.django_db
def test_login_invalid_credentials():
    tenant = Tenant.objects.create(name="T", owner_email="admin@t.com")
    CustomUser.objects.create_user(username="x", email="x@x.com", password="secret", tenant=tenant)

    client = APIClient()
    response = client.post("/api/accounts/login/", {"username": "x", "password": "wrongpass"})
    assert response.status_code == 401

@pytest.mark.django_db
def test_register_duplicate_email():
    tenant = Tenant.objects.create(name="DupCorp", owner_email="dup@dup.com")
    CustomUser.objects.create_user(username="dup", email="dup@dup.com", password="secret", tenant=tenant)

    client = APIClient()
    payload = {
        "company_name": "DupCorp2",
        "email": "dup@dup.com",
        "password": "StrongPassword123"
    }

    response = client.post("/api/accounts/register/", payload)
    assert response.status_code == 400