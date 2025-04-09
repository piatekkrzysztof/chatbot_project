import pytest
from rest_framework.test import APIClient
from accounts.models import CustomUser, Tenant

@pytest.mark.django_db
def test_only_owner_can_create_user():
    tenant = Tenant.objects.create(name="Org", owner_email="x@x.com")
    owner = CustomUser.objects.create_user(username="own", password="x", tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=owner)

    response = client.post("/api/users/", {
        "username": "employee1",
        "email": "emp@x.com",
        "password": "pass",
        "role": "employee"
    })
    assert response.status_code == 201
    assert CustomUser.objects.filter(username="employee1").exists()

@pytest.mark.django_db
def test_employee_cannot_create_user():
    tenant = Tenant.objects.create(name="X", owner_email="x@x.com")
    employee = CustomUser.objects.create_user(username="emp", password="x", tenant=tenant, role="employee")
    client = APIClient()
    client.force_authenticate(user=employee)

    response = client.post("/api/users/", {
        "username": "dupa",
        "email": "bad@x.com",
        "password": "pass",
        "role": "viewer"
    })
    assert response.status_code == 403

@pytest.mark.django_db
def test_user_cannot_access_users_from_another_tenant():
    tenant1 = Tenant.objects.create(name="T1", owner_email="a@t1.com")
    tenant2 = Tenant.objects.create(name="T2", owner_email="a@t2.com")

    user1 = CustomUser.objects.create_user(username="u1", password="x", tenant=tenant1)
    CustomUser.objects.create_user(username="u2", password="x", tenant=tenant2)

    client = APIClient()
    client.force_authenticate(user=user1)

    response = client.get("/api/users/")
    usernames = [u["username"] for u in response.data]
    assert "u2" not in usernames