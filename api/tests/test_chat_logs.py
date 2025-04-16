import pytest
from rest_framework.test import APIClient
from accounts.models import Tenant
from chat.models import PromptLog, ChatMessage, ChatFeedback, Conversation


@pytest.mark.django_db
def test_prompt_logs_endpoint_returns_logs():
    client = APIClient()
    tenant = Tenant.objects.create(name="Firma A", api_key="abc123")
    conv = Conversation.objects.create(id=1, tenant=tenant)

    # 1. Tworzymy PromptLog
    log = PromptLog.objects.create(
        tenant=tenant,
        conversation=conv,
        model="gpt-3.5-turbo",
        source="document",
        tokens=111,
        prompt="Co to jest RODO?",
        response="RODO to rozporządzenie UE.",
    )

    # 2. Tworzymy odpowiadający ChatMessage
    ChatMessage.objects.create(
        conversation=conv,
        sender="bot",
        message=log.response
    )

    res = client.get("/api/chat/logs/", HTTP_X_API_KEY=tenant.api_key)
    assert res.status_code == 200
    data = res.json()

    assert data["count"] == 1
    result = data["results"][0]
    assert result["prompt"] == "Co to jest RODO?"
    assert result["response"] == "RODO to rozporządzenie UE."
    assert result["model"] == "gpt-3.5-turbo"
    assert result["source"] == "document"
    assert result["tokens"] == 111
    assert result["is_helpful"] is None


@pytest.mark.django_db
def test_prompt_logs_endpoint_filters_by_is_helpful():
    client = APIClient()
    tenant = Tenant.objects.create(name="Firma B", api_key="abc456")
    conv = Conversation.objects.create(id=1, tenant=tenant)

    # log 1
    log1 = PromptLog.objects.create(
        tenant=tenant, conversation=conv,
        model="gpt-3.5-turbo", source="gpt", tokens=50,
        prompt="Jak założyć konto?", response="Kliknij przycisk rejestracja"
    )
    msg1 = ChatMessage.objects.create(conversation=conv, sender="bot", message=log1.response)
    ChatFeedback.objects.create(message=msg1, is_helpful=True)

    # log 2
    log2 = PromptLog.objects.create(
        tenant=tenant, conversation=conv,
        model="gpt-3.5-turbo", source="gpt", tokens=60,
        prompt="Co to jest regulamin?", response="Regulamin to dokument..."
    )
    msg2 = ChatMessage.objects.create(conversation=conv, sender="bot", message=log2.response)
    ChatFeedback.objects.create(message=msg2, is_helpful=False)

    # true
    res_true = client.get("/api/chat/logs/?is_helpful=true", HTTP_X_API_KEY=tenant.api_key)
    assert res_true.status_code == 200
    results_true = res_true.json()["results"]
    assert len(results_true) == 1
    assert results_true[0]["is_helpful"] is True

    # false
    res_false = client.get("/api/chat/logs/?is_helpful=false", HTTP_X_API_KEY=tenant.api_key)
    assert res_false.status_code == 200
    results_false = res_false.json()["results"]
    assert len(results_false) == 1
    assert results_false[0]["is_helpful"] is False


@pytest.mark.django_db
def test_prompt_logs_requires_api_key():
    res = APIClient().get("/api/chat/logs/")
    assert res.status_code == 403
