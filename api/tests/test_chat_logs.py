import pytest
from rest_framework.test import APIClient
from accounts.models import Tenant
from chat.models import PromptLog, Conversation, ChatMessage, ChatFeedback


@pytest.mark.django_db
def test_prompt_logs_endpoint_returns_logs():
    client = APIClient()
    tenant = Tenant.objects.create(name="Firma A", owner_email="x@example.com")
    conv = Conversation.objects.create(id=1, tenant=tenant)

    PromptLog.objects.create(
        tenant=tenant,
        conversation=conv,
        model="gpt-3.5-turbo",
        source="document",
        tokens=111,
        prompt="Co to jest RODO?",
        response="RODO to rozporządzenie UE."
    )

    res = client.get("/api/chat/logs/", HTTP_X_API_KEY=tenant.api_key)
    assert res.status_code == 200
    assert isinstance(res.json()["results"], list)
    assert len(res.json()["results"]) == 1
    assert res.json()["results"][0]["prompt"] == "Co to jest RODO?"


@pytest.mark.django_db
def test_prompt_logs_endpoint_filters_by_is_helpful():
    client = APIClient()
    tenant = Tenant.objects.create(name="Firma B", owner_email="y@example.com")
    conv = Conversation.objects.create(id=2, tenant=tenant)

    log1 = PromptLog.objects.create(
        tenant=tenant, conversation=conv,
        model="gpt-3.5-turbo", source="gpt", tokens=50,
        prompt="Jak założyć konto?", response="Kliknij przycisk rejestracja"
    )
    log2 = PromptLog.objects.create(
        tenant=tenant, conversation=conv,
        model="gpt-3.5-turbo", source="gpt", tokens=60,
        prompt="Co to jest regulamin?", response="Regulamin to dokument..."
    )

    msg1 = ChatMessage.objects.create(conversation=conv, sender="bot", message=log1.response)
    msg2 = ChatMessage.objects.create(conversation=conv, sender="bot", message=log2.response)

    ChatFeedback.objects.create(message=msg1, is_helpful=True)
    ChatFeedback.objects.create(message=msg2, is_helpful=False)

    # Sprawdź tylko pomocne
    res_true = client.get("/api/chat/logs/?is_helpful=true", HTTP_X_API_KEY=tenant.api_key)
    results_true = res_true.json()["results"]
    assert len(results_true) == 1
    assert results_true[0]["prompt"] == "Jak założyć konto?"
    assert results_true[0]["is_helpful"] is True

    # Sprawdź tylko niepomocne
    res_false = client.get("/api/chat/logs/?is_helpful=false", HTTP_X_API_KEY=tenant.api_key)
    results_false = res_false.json()["results"]
    assert len(results_false) == 1
    assert results_false[0]["prompt"] == "Co to jest regulamin?"
    assert results_false[0]["is_helpful"] is False


@pytest.mark.django_db
def test_prompt_logs_requires_api_key():
    client = APIClient()
    res = client.get("/api/chat/logs/")
    assert res.status_code == 403
    assert "API key missing" in res.json()["detail"]
