"""
Regresja: formularz dodawania zaproszenia w adminie wywracał się na
`expires_at`, bo pole jest wyliczane z `created_at`, którego niezapisany
obiekt jeszcze nie ma (Sentry: TypeError NoneType + timedelta).
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.models import CustomUser, InvitationToken


def test_expires_at_is_none_before_save(tenant):
    invitation = InvitationToken(tenant=tenant, email="kto@firma.pl", duration="1d")

    assert invitation.expires_at is None


def test_unsaved_invitation_is_not_valid(tenant):
    invitation = InvitationToken(tenant=tenant, email="kto@firma.pl", duration="1d")

    assert invitation.is_valid() is False


@pytest.mark.django_db
def test_expires_at_follows_duration(tenant):
    invitation = InvitationToken.objects.create(tenant=tenant, email="kto@firma.pl", duration="12h")

    delta = invitation.expires_at - invitation.created_at
    assert delta == timedelta(hours=12)


@pytest.mark.django_db
def test_unknown_duration_falls_back_to_one_day(tenant):
    invitation = InvitationToken.objects.create(
        tenant=tenant, email="kto@firma.pl", duration="dziwne"
    )

    assert invitation.expires_at - invitation.created_at == timedelta(days=1)


@pytest.mark.django_db
def test_expired_invitation_is_not_valid(tenant):
    invitation = InvitationToken.objects.create(tenant=tenant, email="kto@firma.pl", duration="1h")
    InvitationToken.objects.filter(pk=invitation.pk).update(
        created_at=timezone.now() - timedelta(hours=2)
    )
    invitation.refresh_from_db()

    assert invitation.is_valid() is False


@pytest.mark.django_db
def test_invitation_exhausted_by_use_is_not_valid(tenant):
    invitation = InvitationToken.objects.create(
        tenant=tenant, email="kto@firma.pl", duration="7d", max_users=1
    )
    invitation.use()

    assert invitation.is_valid() is False


@pytest.mark.django_db
def test_admin_add_form_opens(client, tenant):
    """Dokładny scenariusz z alertu: GET na /admin/accounts/invitationtoken/add/."""
    admin = CustomUser.objects.create_superuser(
        username="admin@firma.pl", email="admin@firma.pl", password="Tajne123!", tenant=tenant
    )
    client.force_login(admin)

    response = client.get("/admin/accounts/invitationtoken/add/")

    assert response.status_code == 200
