import uuid

import pytest
from django.core import mail
from rest_framework.test import APIClient

from chat.models import ContactRequest, Conversation


@pytest.mark.django_db
def test_visitor_can_leave_contact_without_login(tenant):
    """Odwiedzający strony klienta nie ma konta — endpoint musi działać na sam klucz API."""
    client = APIClient()
    response = client.post(
        "/api/widget/contact/",
        {"name": "Jan", "contact": "jan@firma.pl", "message": "Pytanie o dostawy"},
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
    )

    assert response.status_code == 201
    request = ContactRequest.objects.get()
    assert request.tenant == tenant
    assert request.contact == "jan@firma.pl"
    assert request.handled is False


@pytest.mark.django_db
def test_contact_is_linked_to_conversation(tenant):
    conversation = Conversation.objects.create(tenant=tenant, user_identifier="a")

    APIClient().post(
        "/api/widget/contact/",
        {"contact": "500100200", "conversation_session_id": str(conversation.session_id)},
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
    )

    assert ContactRequest.objects.get().conversation == conversation


@pytest.mark.django_db
def test_contact_requires_valid_api_key():
    response = APIClient().post(
        "/api/widget/contact/",
        {"contact": "jan@firma.pl"},
        format="json",
        HTTP_X_API_KEY=str(uuid.uuid4()),
    )
    assert response.status_code == 401
    assert ContactRequest.objects.count() == 0


@pytest.mark.django_db
def test_contact_notifies_the_company(tenant):
    tenant.owner_email = "wlasciciel@firma.pl"
    tenant.save()

    APIClient().post(
        "/api/widget/contact/",
        {"contact": "jan@firma.pl"},
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
    )

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["wlasciciel@firma.pl"]


@pytest.mark.django_db
def test_panel_lists_only_own_requests(user, tenant, subscribtion):
    from .factories import TenantFactory

    other = TenantFactory()
    ContactRequest.objects.create(tenant=tenant, contact="moj@klient.pl")
    ContactRequest.objects.create(tenant=other, contact="cudzy@klient.pl")

    user.tenant = tenant
    user.role = "owner"
    user.save()
    client = APIClient()
    client.force_authenticate(user=user)

    data = client.get("/api/contact-requests/", HTTP_X_API_KEY=str(tenant.api_key)).json()

    assert [r["contact"] for r in data] == ["moj@klient.pl"]


@pytest.mark.django_db
def test_panel_can_mark_as_handled(user, tenant, subscribtion):
    request = ContactRequest.objects.create(tenant=tenant, contact="jan@firma.pl")

    user.tenant = tenant
    user.role = "owner"
    user.save()
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.patch(
        f"/api/contact-requests/{request.id}/",
        {"handled": True},
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
    )

    assert response.status_code == 200
    request.refresh_from_db()
    assert request.handled is True
