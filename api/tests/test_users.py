import pytest
from rest_framework.test import APIClient
from accounts.models import CustomUser, Tenant, Subscription
from datetime import date, timedelta
from chat.models import Conversation


# @pytest.fixture
# def tenant2():
#     return Tenant.objects.create(
#         name="TestTenant2",
#         owner_email="test@example.com"
#     )
#
#
# @pytest.fixture
# def conversation2(tenant):
#     return Conversation.objects.create(
#         tenant=tenant,
#         user_identifier="test-user",
#     )
#
#
# @pytest.fixture
# def subscribtion2(tenant2):
#     return Subscription.objects.create(
#         tenant=tenant2,
#         is_active=True,
#         start_date=date.today() - timedelta(days=1),
#         end_date=date.today() + timedelta(days=30),
#     )
#
#
# @pytest.fixture
# def user2(tenant):
#     return CustomUser.objects.create_user(
#         username="xd", email="x@x.com", password="secret", tenant=tenant
#     )
#
#
# @pytest.fixture
# def api_client(tenant):
#     client = APIClient()
#     client.credentials(HTTP_X_API_KEY=str(tenant.api_key))
#
#     return client


@pytest.mark.django_db
def test_only_owner_can_create_user(api_client, tenant, user, subscribtion):
    user.tenant = tenant
    user.role = "owner"
    user.save()
    api_client.force_authenticate(user=user)

    response = api_client.post("/api/users/", {
        "username": "employee1",
        "email": "emp@x.com",
        "password": "pass",
        "role": "employee"
    }, HTTP_X_API_KEY=tenant.api_key)
    assert response.status_code == 201
    assert CustomUser.objects.filter(username="employee1").exists()


@pytest.mark.django_db
def test_employee_cannot_create_user(api_client, tenant, user, subscribtion):
    user.tenant = tenant
    user.role = "employee"
    user.save()
    api_client.force_authenticate(user=user)

    response = api_client.post("/api/users/", {
        "username": "dupa",
        "email": "bad@x.com",
        "password": "pass",
        "role": "viewer"
    }, HTTP_X_API_KEY=tenant.api_key)
    assert response.status_code == 403


@pytest.mark.django_db
def test_user_cannot_access_users_from_another_tenant(api_client, tenant, user, subscribtion,):
    tenant2 = Tenant.objects.create(name="T2", owner_email="a@t2.com")
    Subscription.objects.create(
        tenant=tenant2,
        is_active=True,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=30),
    )

    CustomUser.objects.create_user(username="u2", password="x", tenant=tenant2)

    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/users/", HTTP_X_API_KEY=tenant.api_key)
    usernames = [u["username"] for u in response.data]
    assert "u2" not in usernames
