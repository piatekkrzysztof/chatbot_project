import pytest
from rest_framework.test import APIClient
from chat.models import Conversation, PromptLog, ChatMessage, ChatFeedback
from accounts.models import Tenant, CustomUser, Subscription


@pytest.mark.django_db
def test_prompt_logs_endpoint_returns_logs(user, tenant, subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.role = "owner"
    user.save()
    tenant.save()
    client.force_authenticate(user=user)

    conv = Conversation.objects.create(tenant=tenant, user_identifier="test-user")
    PromptLog.objects.create(
        tenant=tenant,
        conversation=conv,
        model="gpt-3.5-turbo",
        source="document",
        tokens=111,
        prompt="Co to jest RODO?",
        response="RODO to rozporządzenie UE."
    )

    res = client.get("/api/chat/logs/", HTTP_X_API_KEY=str(tenant.api_key))
    assert res.status_code == 200
    assert isinstance(res.data[0], dict)
    assert res.data[0]["prompt"] == "Co to jest RODO?"


@pytest.mark.django_db
def test_prompt_logs_endpoint_filters_by_is_helpful(user, tenant, subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.role = "employee"
    user.save()
    tenant.save()
    client.force_authenticate(user=user)

    conv = Conversation.objects.create(tenant=tenant, user_identifier="abc")

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

    res_true = client.get("/api/chat/logs/?is_helpful=true", HTTP_X_API_KEY=str(tenant.api_key))
    assert res_true.status_code == 200
    prompts_true = [r["prompt"] for r in res_true.data]
    assert "Jak założyć konto?" in prompts_true

    res_false = client.get("/api/chat/logs/?is_helpful=false", HTTP_X_API_KEY=str(tenant.api_key))
    assert res_false.status_code == 200
    prompts_false = [r["prompt"] for r in res_false.data]
    assert "Co to jest regulamin?" in prompts_false


@pytest.mark.django_db
def test_prompt_logs_requires_api_key(tenant,user,subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.role = "employee"
    user.save()
    tenant.save()
    client.force_authenticate(user=user)
    client = APIClient()
    res = client.get("/api/chat/logs/",HTTP_X_API_KEY=str(tenant.api_key))
    assert res.status_code == 403
