from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from chat.models import FAQ, ChatMessage, Conversation, PromptLog


def auth_client(user, tenant, role="owner"):
    user.tenant = tenant
    user.role = role
    user.save()
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_analytics_counts_only_own_tenant(user, tenant, subscribtion):
    from .factories import TenantFactory

    other = TenantFactory()
    mine = Conversation.objects.create(tenant=tenant, user_identifier="a")
    Conversation.objects.create(tenant=other, user_identifier="b")

    ChatMessage.objects.create(conversation=mine, sender="user", message="Pytanie")
    ChatMessage.objects.create(conversation=mine, sender="bot", message="Odpowiedź")

    client = auth_client(user, tenant)
    response = client.get("/api/analytics/", HTTP_X_API_KEY=str(tenant.api_key))

    assert response.status_code == 200
    data = response.json()
    assert data["conversations"]["total"] == 1
    assert data["questions"]["total"] == 1


@pytest.mark.django_db
def test_analytics_returns_daily_question_counts(user, tenant, subscribtion):
    conversation = Conversation.objects.create(tenant=tenant, user_identifier="a")
    ChatMessage.objects.create(
        conversation=conversation,
        sender="user",
        message="Dzisiaj",
    )
    two_days_ago_message = ChatMessage.objects.create(
        conversation=conversation,
        sender="user",
        message="Dwa dni temu",
    )
    ChatMessage.objects.filter(pk=two_days_ago_message.pk).update(
        timestamp=timezone.now() - timedelta(days=2),
    )

    client = auth_client(user, tenant)
    daily = client.get(
        "/api/analytics/",
        HTTP_X_API_KEY=str(tenant.api_key),
    ).json()["questions"]["daily"]

    assert len(daily) == 7
    assert daily[-1]["date"] == timezone.localdate().isoformat()
    assert daily[-1]["count"] == 1
    assert daily[-3]["count"] == 1
    assert sum(day["count"] for day in daily) == 2


@pytest.mark.django_db
def test_analytics_reports_unanswered_questions(user, tenant, subscribtion):
    conversation = Conversation.objects.create(tenant=tenant, user_identifier="a")
    PromptLog.objects.create(
        tenant=tenant,
        conversation=conversation,
        model="test",
        prompt="Czy robicie dostawy za granice?",
        response="Nie wiem.",
        source="gpt",
        tokens=10,
    )
    PromptLog.objects.create(
        tenant=tenant,
        conversation=conversation,
        model="test",
        prompt="Ile kosztuje przeglad?",
        response="120 zl",
        source="document",
        tokens=10,
    )

    client = auth_client(user, tenant)
    data = client.get("/api/analytics/", HTTP_X_API_KEY=str(tenant.api_key)).json()

    assert data["answer_sources"]["gpt"] == 1
    assert data["answer_sources"]["document"] == 1
    assert [q["question"] for q in data["unanswered"]] == ["Czy robicie dostawy za granice?"]


@pytest.mark.django_db
def test_analytics_reports_plan_usage(user, tenant, subscribtion):
    subscribtion.current_message_count = 7
    subscribtion.message_limit = 100
    subscribtion.plan_type = "pro"
    subscribtion.save()

    client = auth_client(user, tenant)
    data = client.get("/api/analytics/", HTTP_X_API_KEY=str(tenant.api_key)).json()

    assert data["usage"] == {"used": 7, "limit": 100, "plan": "pro"}


@pytest.mark.django_db
def test_analytics_includes_tenant_name(user, tenant, subscribtion):
    client = auth_client(user, tenant)

    data = client.get(
        "/api/analytics/",
        HTTP_X_API_KEY=str(tenant.api_key),
    ).json()

    assert data["tenant_name"] == tenant.name


@pytest.mark.django_db
def test_faq_create_is_scoped_to_tenant(user, tenant, subscribtion):
    client = auth_client(user, tenant)
    response = client.post(
        "/api/faq/",
        {"question": "Godziny otwarcia?", "answer": "9-17"},
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
    )

    assert response.status_code == 201
    faq = FAQ.objects.get()
    assert faq.tenant == tenant


@pytest.mark.django_db
def test_faq_list_hides_other_tenants(user, tenant, subscribtion):
    from .factories import TenantFactory

    other = TenantFactory()
    FAQ.objects.create(tenant=tenant, question="Moje", answer="tak")
    FAQ.objects.create(tenant=other, question="Cudze", answer="nie")

    client = auth_client(user, tenant)
    data = client.get("/api/faq/", HTTP_X_API_KEY=str(tenant.api_key)).json()

    assert [f["question"] for f in data] == ["Moje"]


@pytest.mark.django_db
def test_faq_delete(user, tenant, subscribtion):
    faq = FAQ.objects.create(tenant=tenant, question="Do usuniecia", answer="x")

    client = auth_client(user, tenant)
    response = client.delete(f"/api/faq/{faq.id}/", HTTP_X_API_KEY=str(tenant.api_key))

    assert response.status_code == 204
    assert FAQ.objects.count() == 0


@pytest.mark.django_db
def test_faq_requires_authentication(tenant):
    client = APIClient()
    response = client.get("/api/faq/", HTTP_X_API_KEY=str(tenant.api_key))
    assert response.status_code in (401, 403)
