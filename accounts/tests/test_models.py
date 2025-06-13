import pytest
from accounts.models import Tenant, CustomUser, InvitationToken
from django.utils import timezone
from datetime import timedelta


@pytest.mark.django_db
def test_tenant_str():
    tenant = Tenant.objects.create(name="TestCorp", owner_email="a@b.com")
    assert str(tenant.name) == "TestCorp"


@pytest.mark.django_db
def test_invitation_token_validity():
    tenant = Tenant.objects.create(name="Org", owner_email="o@o.com")
    token = InvitationToken.objects.create(
        tenant=tenant,
        role="employee",
        duration=24,
        max_users=1,
        email="invite@org.com"
    )
    assert token.is_valid() is True
    assert token.users == 0

    token.use()
    assert token.users == 1
    assert token.is_valid() is False


@pytest.mark.django_db
def test_invitation_token_expired():
    tenant = Tenant.objects.create(name="T", owner_email="x@x.com")
    token = InvitationToken.objects.create(
        tenant=tenant, role="employee", duration=1, max_users=1
    )
    token.created_at = timezone.now() - timedelta(hours=2)
    token.save()
    assert not token.is_valid()


@pytest.mark.django_db
def test_invitation_token_overused():
    tenant = Tenant.objects.create(name="T", owner_email="x@x.com")
    token = InvitationToken.objects.create(
        tenant=tenant, role="employee", duration=24, max_users=1, users=1
    )
    assert token.is_valid() is False


@pytest.mark.django_db
def test_token_str_repr():
    tenant = Tenant.objects.create(name="Corp", owner_email="corp@x.com")
    token = InvitationToken.objects.create(tenant=tenant, role="viewer", duration=24)
    assert str(token) == f"Invitation for {token.email} [{token.role}] ({token.tenant.name})"



@pytest.mark.django_db
def test_user_str_repr():
    tenant = Tenant.objects.create(name="A", owner_email="a@a.com")
    user = CustomUser.objects.create_user(username="x", email="x@x.com", password="123", tenant=tenant)
    assert str(user) == "x [A]"
