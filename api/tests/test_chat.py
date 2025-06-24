import pytest
from rest_framework.test import APIClient
from accounts.models import Tenant
from chat.models import Conversation
import uuid

@pytest.fixture
def tenant(db):
    t = Tenant.objects.create(
        name="TestTenant",
        owner_email="test@example.com"
    )
    print("TENANT KEY W FIXTURE:", t.api_key)
    return t

@pytest.fixture
def api_client(tenant):
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=str(tenant.api_key))
    print("API KEY W API_CLIENT:", tenant.api_key)
    return client

def test_manual_tenant_check(db):
    t = Tenant.objects.create(name="SanityTenant", owner_email="sanity@example.com")
    fetched = Tenant.objects.get(api_key=t.api_key)
    assert fetched.id == t.id

@pytest.mark.django_db
def test_chat_view_success(api_client, tenant):
    conversation = Conversation.objects.create(
        tenant=tenant,
        user_identifier="test-user"
    )
    payload = {
        "message": "Jak mogę skontaktować się z Wami?",
        "conversation__session_id": str(conversation.session_id)
    }
    response = api_client.post("/api/chat/", payload, format="json")
    assert response.status_code == 200
    assert "response" in response.data

@pytest.mark.django_db
def test_chat_view_invalid_api_key():
    client = APIClient()
    payload = {
        "message": "Test",
        "conversation_id": str(uuid.uuid4())
    }
    # generuj poprawny (ale losowy) UUID
    client.credentials(HTTP_X_API_KEY=str(uuid.uuid4()))
    response = client.post("/api/chat/", payload, format="json")
    # spodziewaj się 403 (bo key poprawny format, ale nie w bazie)
    assert response.status_code == 403

@pytest.mark.django_db
def test_chat_view_missing_api_key():
    client = APIClient()
    payload = {
        "message": "Test",
        "conversation_id": str(uuid.uuid4())
    }
    response = client.post("/api/chat/", payload, format="json")
    assert response.status_code == 401 or response.status_code == 403

@pytest.mark.django_db
def test_chat_view_invalid_payload(api_client):
    payload = {
        "wrong_field": "value"
    }
    response = api_client.post("/api/chat/", payload, format="json")
    # Jeśli autoryzacja przejdzie, powinien być 400 za zły payload
    assert response.status_code == 400

@pytest.mark.django_db
def test_chat_view_new_conversation(api_client, tenant):
    payload = {
        "message": "Cześć, chcę założyć nowe zgłoszenie!"
        # nie podajemy conversation_id, żeby wymusić utworzenie nowej konwersacji
    }
    response = api_client.post("/api/chat/", payload, format="json")
    assert response.status_code == 200
    assert "response" in response.data
    assert "conversation_id" in response.data

# TEST Z MOCKIEM - wymaga pytest-mock (pip install pytest-mock)
@pytest.mark.django_db
def test_chat_view_openai_fallback(api_client, tenant, mocker):
    mock_engine = mocker.patch("api.utils.chat_engine.generate_gpt_response")
    mock_engine.return_value = "Testowa odpowiedź fallback"
    conversation = Conversation.objects.create(
        tenant=tenant,
        user_identifier="test-user"
    )
    payload = {
        "message": "Testowe zapytanie do fallbacku",
        "conversation_id": str(conversation.id)
    }
    response = api_client.post("/api/chat/", payload, format="json")
    assert response.status_code == 200
    assert response.data["response"] == "Testowa odpowiedź fallback"
