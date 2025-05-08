import pytest
from rest_framework.test import APIClient
from django.core.cache import cache
from accounts.models import Tenant
from chat.models import Conversation
from unittest.mock import patch


@pytest.fixture
def tenant():
    return Tenant.objects.create(name="TestTenant", owner_email="test@test.com")


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


@pytest.mark.django_db
def test_faq_response(client, tenant):
    faq = tenant.faqs.create(question="Jak się kontaktować?", answer="Poprzez formularz kontaktowy.")
    response = client.post("/api/chat/", {
        "conversation_id": "1",
        "message": "Jak się kontaktować?"
    }, HTTP_X_API_KEY=tenant.api_key)
    assert response.status_code == 200
    assert "formularz" in response.data["response"].lower()


@pytest.mark.django_db
@patch("api.views.chat.search_documents_chroma")
@patch("api.views.chat.get_openai_response")
def test_document_response(mock_gpt, mock_search, client, tenant):
    mock_search.return_value = ["Suplement przechowuj w 25°C."]
    mock_gpt.return_value = {
        "content": "Przechowuj suplementy w maksymalnie 25 stopniach.",
        "tokens": 45
    }

    response = client.post("/api/chat/", {
        "conversation_id": "2",
        "message": "Gdzie trzymać suplementy?"
    }, HTTP_X_API_KEY=tenant.api_key)

    assert response.status_code == 200
    assert "25" in response.data["response"]


@pytest.mark.django_db
@patch("api.views.chat.get_openai_response")
def test_gpt_response(mock_gpt, client, tenant):
    mock_gpt.return_value = {
        "content": "To zależy od kontekstu.",
        "tokens": 28
    }

    response = client.post("/api/chat/", {
        "conversation_id": "3",
        "message": "Jaka jest prędkość światła?"
    }, HTTP_X_API_KEY=tenant.api_key)

    assert response.status_code == 200
    assert "kontekstu" in response.data["response"]


@pytest.mark.django_db
def test_missing_api_key(client):
    response = client.post("/api/chat/", {
        "conversation_id": "4",
        "message": "Cokolwiek"
    })
    assert response.status_code == 403


@pytest.mark.django_db
@patch("chat.utils.openai_helpers.get_openai_response")
def test_rate_limiting(mock_gpt, client, tenant):
    cache.clear()
    mock_gpt.return_value = {
        "content": "Test GPT.",
        "tokens": 10
    }

    for _ in range(11):
        response = client.post("/api/chat/", {
            "conversation_id": "999",
            "message": "trigger"
        }, HTTP_X_API_KEY=tenant.api_key)

    assert response.status_code == 429
