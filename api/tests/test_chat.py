import pytest
from rest_framework.test import APIClient
from accounts.models import Tenant
from unittest.mock import patch

from chat.models import Conversation


@pytest.fixture
def tenant():
    return Tenant.objects.create(name="TestTenant", api_key="testkey123", owner_email="test@test.com")


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
@patch("api.views.chat.get_openai_response")
def test_chat_view_success(mock_openai, client, tenant):
    mock_openai.return_value = {
        "content": "Oto odpowiedź z GPT",
        "tokens": 42
    }
    conversation = Conversation.objects.create(tenant=tenant, user_identifier="test-ip")

    payload = {
        "message": "Jak mogę się z Wami skontaktować?",
        "conversation_id": str(conversation.id)
    }

    response = client.post("/api/chat/", payload, HTTP_X_API_KEY=tenant.api_key)
    assert response.status_code == 200
    assert "response" in response.data
    assert "GPT" not in response.data["response"].lower()  # sprawdź treść zależnie od mocka


@pytest.mark.django_db
def test_chat_view_regulamin(client, tenant):
    tenant.regulamin = "To jest regulamin"
    tenant.save()
    conversation = Conversation.objects.create(tenant=tenant, user_identifier="test-ip")

    response = client.post("/api/chat/", {
        "message": "regulamin",
        "conversation_id": str(conversation.id)
    }, HTTP_X_API_KEY=tenant.api_key)

    assert response.status_code == 200
    assert "regulamin" in response.data["response"].lower()


@pytest.mark.django_db
def test_chat_view_missing_api_key(client):
    response = client.post("/api/chat/", {
        "message": "Test",
        "conversation_id": "conv-999"
    })
    assert response.status_code == 403


@pytest.mark.django_db
def test_chat_view_invalid_api_key(client):
    response = client.post("/api/chat/", {
        "message": "Test",
        "conversation_id": "conv-999"
    }, HTTP_X_API_KEY="invalid123")

    assert response.status_code == 403


@pytest.mark.django_db
@patch("api.views.chat.get_openai_response", side_effect=Exception("OpenAI timeout"))
def test_chat_view_openai_error_handling(mock_openai, client, tenant):
    conversation = Conversation.objects.create(tenant=tenant, user_identifier="test-ip")
    response = client.post("/api/chat/", {
        "message": "Cokolwiek",
        "conversation_id": str(conversation.id)
    }, HTTP_X_API_KEY=tenant.api_key)

    assert response.status_code == 200
    assert "błąd" in response.data["response"].lower()
