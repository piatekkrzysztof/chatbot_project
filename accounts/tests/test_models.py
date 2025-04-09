import pytest
from accounts.models import Tenant, CustomUser, InvitationToken
from django.utils import timezone
from datetime import timedelta


@pytest.mark.django_db
def test_tenant_str():
    tenant = Tenant.objects.create(name="TestCorp", owner_email="a@b.com")
    assert str(tenant) == "TestCorp"


@pytest.mark.django_db
def test_custom_user_is_owner():
    tenant = Tenant.objects.create(name="Org", owner_email="o@o.com")
    user = CustomUser.objects.create(username="u", password = "test", tenant=tenant, role="owner")
    assert user.is_owner is True


@pytest.mark.django_db
def test_invitation_token_validity():
    tenant = Tenant.objects.create(name="Org", owner_email="o@o.com")
    token = InvitationToken.objects.create(
        tenant=tenant,
        role="employee",
        duration_hours=24,
        max_uses=1,
        email="invite@org.com"
    )
    assert token.is_valid() is True
    assert token.uses == 0

    token.use()
    assert token.uses == 1
    assert token.is_valid() is False
