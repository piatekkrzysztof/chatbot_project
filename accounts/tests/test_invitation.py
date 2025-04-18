from datetime import timedelta

import pytest
from django.utils import timezone
from accounts.models import Tenant, InvitationToken


@pytest.mark.django_db
def test_invitation_token_is_valid_initially():
    tenant = Tenant.objects.create(name="Firma Testowa")
    token = InvitationToken.objects.create(tenant=tenant, email="test@example.com")

    assert token.is_valid() is True


@pytest.mark.django_db
def test_invitation_token_expires_correctly():
    tenant = Tenant.objects.create(name="Firma")
    token = InvitationToken.objects.create(tenant=tenant, email="test@example.com", duration="1h")
    token.created_at = timezone.now() - timedelta(hours=2)
    token.save(update_fields=["created_at"])

    assert token.is_valid() is False


@pytest.mark.django_db
def test_invitation_token_usage_limit():
    tenant = Tenant.objects.create(name="Firma")
    token = InvitationToken.objects.create(tenant=tenant, email="test@example.com", max_users=1, users=1)

    assert token.is_valid() is False
