import pytest
from rest_framework.test import APIClient
from accounts.models import Tenant, CustomUser
from chat.models import Conversation
import uuid
from rest_framework.exceptions import AuthenticationFailed

@pytest.fixture
def tenant(db):
    return Tenant.objects.create(
        name="TestTenant",
        owner_email="test@example.com"
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
def test_chat_view_success(api_client, tenant,user):
    conversation = Conversation.objects.create(
        tenant=tenant,
        user_identifier="test-user"
    )
    payload = {
        "message": "Jak mogę skontaktować się z Wami?",
        "conversation_id": 1,
        "conversation_session_id": str(conversation.session_id),
    }
    api_client.force_authenticate(user=user, )
    response = api_client.post("/api/chat/", payload, format="json")
    assert response.status_code == 200
    assert "response" in response.data

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
def test_chat_view_new_conversation(api_client):
    payload = {
        "message": "Cześć, chcę założyć nowe zgłoszenie!"
    }
    response = api_client.post("/api/chat/", payload, format="json")
    assert response.status_code == 200
    assert "response" in response.data
    assert "conversation_id" in response.data

@pytest.mark.django_db
def test_chat_view_openai_fallback(api_client, tenant, mocker):
    mock_engine = mocker.patch("api.utils.chat_engine.process_chat_message")
    mock_engine.return_value = "Testowa odpowiedź fallback"
    conversation = Conversation.objects.create(
        tenant=tenant,
        user_identifier="test-user"
    )
    payload = {
        "message": "Testowe zapytanie do fallbacku",
        "conversation_id": str(conversation.session_id)
    }
    response = api_client.post("/api/chat/", payload, format="json")
    assert response.status_code == 200
    assert response.data["response"] == "Testowa odpowiedź fallback"
