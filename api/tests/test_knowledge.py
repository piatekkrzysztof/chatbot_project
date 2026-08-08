"""
Opis działalności firmy w panelu oraz raport braku wiedzy w analityce.

Opis firmy dało się wcześniej ustawić wyłącznie w Django adminie, więc klient
nie miał jak opisać własnej działalności — a bez niego bot odmawia odpowiedzi
na najczęstsze pytanie w ogóle. Analityka musi ten brak nazwać wprost, inaczej
właściciel widzi tylko bota, który "nic nie umie".
"""
import pytest
from rest_framework.test import APIClient

from chat.models import FAQ
from documents.models import Document


def auth_client(user, tenant, role="owner"):
    user.tenant = tenant
    user.role = role
    user.save()
    client = APIClient()
    client.force_authenticate(user=user)
    # TenantMiddleware rozwiązuje tenanta po nagłówku, zanim żądanie dotrze do widoku
    client.credentials(HTTP_X_API_KEY=str(tenant.api_key))
    return client


@pytest.mark.django_db
def test_owner_can_read_and_save_company_description(user, tenant):
    client = auth_client(user, tenant)

    response = client.patch(
        "/api/knowledge/",
        {"gpt_prompt": "Sprzedajemy rowery elektryczne."},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["gpt_prompt"] == "Sprzedajemy rowery elektryczne."

    tenant.refresh_from_db()
    assert tenant.gpt_prompt == "Sprzedajemy rowery elektryczne."


@pytest.mark.django_db
def test_knowledge_patch_leaves_untouched_fields_alone(user, tenant):
    tenant.regulamin = "Zwroty w 14 dni."
    tenant.save()
    client = auth_client(user, tenant)

    client.patch("/api/knowledge/", {"gpt_prompt": "Nowy opis."}, format="json")

    tenant.refresh_from_db()
    assert tenant.regulamin == "Zwroty w 14 dni."


@pytest.mark.django_db
def test_knowledge_endpoint_rejects_other_tenants_data(user, tenant):
    """Widok operuje na tenancie z tokenu, nigdy na id z żądania."""
    from .factories import TenantFactory

    other = TenantFactory()
    client = auth_client(user, tenant)

    client.patch(
        "/api/knowledge/",
        {"gpt_prompt": "Podmieniony", "tenant": other.id},
        format="json",
    )

    other.refresh_from_db()
    tenant.refresh_from_db()
    assert tenant.gpt_prompt == "Podmieniony"
    assert other.gpt_prompt != "Podmieniony"


@pytest.mark.django_db
def test_analytics_flags_completely_empty_knowledge(user, tenant, subscribtion):
    tenant.gpt_prompt = ""
    tenant.save()
    client = auth_client(user, tenant)

    knowledge = client.get("/api/analytics/").json()["knowledge"]

    assert knowledge["is_empty"] is True
    assert knowledge["has_description"] is False


@pytest.mark.django_db
def test_analytics_stops_flagging_after_description_added(user, tenant, subscribtion):
    tenant.gpt_prompt = "Sprzedajemy rowery."
    tenant.save()
    client = auth_client(user, tenant)

    knowledge = client.get("/api/analytics/").json()["knowledge"]

    assert knowledge["is_empty"] is False
    assert knowledge["has_description"] is True


@pytest.mark.django_db
def test_faq_alone_clears_the_empty_flag(user, tenant, subscribtion):
    tenant.gpt_prompt = ""
    tenant.save()
    FAQ.objects.create(tenant=tenant, question="Godziny?", answer="9-17.")
    client = auth_client(user, tenant)

    assert client.get("/api/analytics/").json()["knowledge"]["is_empty"] is False


@pytest.mark.django_db
def test_unprocessed_document_does_not_count_as_knowledge(user, tenant, subscribtion):
    """
    Dokument bez fragmentów nie trafił jeszcze do wyszukiwania, więc bot z niego
    nie korzysta — panel nie może udawać, że wiedza już jest.
    """
    tenant.gpt_prompt = ""
    tenant.save()
    Document.objects.create(tenant=tenant, name="cennik.pdf", content="")
    client = auth_client(user, tenant)

    knowledge = client.get("/api/analytics/").json()["knowledge"]

    assert knowledge["documents"] == 1
    assert knowledge["indexed_chunks"] == 0
    assert knowledge["is_empty"] is True
