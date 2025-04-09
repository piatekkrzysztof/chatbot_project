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