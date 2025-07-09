import pytest
from rest_framework.test import APIClient
from accounts.models import Tenant, CustomUser
from chat.models import Conversation
import uuid
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from accounts.models import Subscription
from datetime import date, timedelta
from .factories import TenantFactory, UserFactory, SubscriptionFactory, ConversationFactory, ChatMessageFactory
from unittest.mock import patch


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(
        name="TestTenant",
        owner_email="test@example.com"
    )


@pytest.fixture
def subscribtion(db, tenant):
    return Subscription.objects.create(
        tenant=tenant,
        is_active=True,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=30),
    )


@pytest.fixture
def user(db, tenant):
    return CustomUser.objects.create_user(
        username="x", email="x@x.com", password="secret", tenant=tenant
    )


@pytest.fixture
def api_client(tenant):
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=str(tenant.api_key))

    return client


@pytest.mark.django_db
def test_chat_view_success(api_client, tenant, user, subscribtion):
    user.tenant = tenant
    user.save()
    api_client.force_authenticate(user=user)

    conversation = Conversation.objects.create(
        tenant=tenant,
        user_identifier="test-user"
    )
    payload = {
        "message": "Jak mogę skontaktować się z Wami?",
        "conversation_id": conversation.id,
        "conversation_session_id": str(conversation.session_id),
    }

    # Wysyłamy żądanie
    headers = {"HTTP_X_API_KEY": tenant.api_key}
    response = api_client.post("/api/chat/", payload, format="json", **headers)

    # Symulujemy przypisanie request.tenant ręcznie jeśli middleware nie zadziała
    request = Request(response.wsgi_request)
    request.tenant = tenant

    assert response.status_code == 200


@pytest.mark.django_db
def test_chat_view_invalid_api_key():
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=str(uuid.uuid4()))
    payload = {
        "message": "Test",
        "conversation_id": str(uuid.uuid4())
    }
    with pytest.raises(AuthenticationFailed):
        client.post("/api/chat/", payload, format="json")


@pytest.mark.django_db
def test_chat_view_missing_api_key():
    client = APIClient()
    payload = {
        "message": "Test",
        "conversation_id": str(uuid.uuid4())
    }
    with pytest.raises(AuthenticationFailed):
        client.post("/api/chat/", payload, format="json")


@pytest.mark.django_db
def test_chat_view_invalid_payload(api_client):
    payload = {
        "wrong_field": "value"
    }
    response = api_client.post("/api/chat/", payload, format="json")
    assert response.status_code in [400, 403]  # zależnie od logiki serializera lub middleware


@pytest.mark.django_db
def test_chat_view_new_conversation(api_client, user, tenant, subscribtion):
    user.tenant = tenant
    user.save()
    api_client.force_authenticate(user=user)

    conversation = Conversation.objects.create(
        tenant=tenant,
        user_identifier="test-user"
    )

    payload = {
        "message": "Cześć, chcę założyć nowe zgłoszenie!",
        "conversation_id": conversation.id,
        "conversation_session_id": str(conversation.session_id),
    }

    headers = {"HTTP_X_API_KEY": tenant.api_key}
    response = api_client.post("/api/chat/", payload, format="json", **headers)
    assert response.status_code == 200
    assert "response" in response.data


@pytest.mark.django_db
def test_chat_view_openai_fallback(api_client, user, tenant, subscribtion):
    user.tenant = tenant
    user.save()
    api_client.force_authenticate(user=user)

    conversation = Conversation.objects.create(
        tenant=tenant,
        user_identifier="test-user"
    )

    payload = {
        "message": "Testowe zapytanie do fallbacku",
        "conversation_id": conversation.id,
        "conversation_session_id": str(conversation.session_id),
    }

    with patch("api.views.chat.process_chat_message", return_value={
        "response": "Testowa odpowiedź fallback",
        "source": "gpt",
        "tokens": 0
    }):
        headers = {"HTTP_X_API_KEY": tenant.api_key}
        response = api_client.post("/api/chat/", payload, format="json", **headers)

    assert response.status_code == 200
    assert response.data["response"] == "Testowa odpowiedź fallback"


@pytest.mark.django_db
def test_chat_view_enforces_subscription_limit(user, tenant, conversation, subscribtion):
    client = APIClient()
    client.force_authenticate(user=user)
    client.defaults["HTTP_X_API_KEY"] = str(tenant.api_key)

    subscribtion.plan_type = "free"

    for i in range(20):
        res = client.post("/api/chat/", {
            "message": "test",
            "conversation_id": conversation.id,
            "conversation_session_id": str(conversation.session_id),
        }, format="json")
        assert res.status_code == 200

    # 21st should fail
    res = client.post("/api/chat/", {
        "message": "test",
        "conversation_id": conversation.id,
        "conversation_session_id": str(conversation.session_id),
    }, format="json")
    assert res.status_code == 429
