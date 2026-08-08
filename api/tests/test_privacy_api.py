"""
Endpointy RODO w panelu: okres retencji i prawo do bycia zapomnianym.
"""
import pytest
from rest_framework.test import APIClient

from chat.models import ChatMessage, ChatUsageLog, ContactRequest, Conversation, PromptLog


def auth_client(user, tenant, role="owner"):
    user.tenant = tenant
    user.role = role
    user.save()
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_API_KEY=str(tenant.api_key))
    return client


@pytest.mark.django_db
def test_owner_ustawia_okres_retencji(user, tenant):
    client = auth_client(user, tenant)

    response = client.patch("/api/privacy/", {"data_retention_days": 30}, format="json")

    assert response.status_code == 200
    tenant.refresh_from_db()
    assert tenant.data_retention_days == 30


@pytest.mark.django_db
def test_ujemna_retencja_jest_odrzucana(user, tenant):
    client = auth_client(user, tenant)

    response = client.patch("/api/privacy/", {"data_retention_days": -5}, format="json")

    assert response.status_code == 400
    tenant.refresh_from_db()
    assert tenant.data_retention_days != -5


@pytest.mark.django_db
def test_niebedaca_liczba_retencja_nie_wywala_serwera(user, tenant):
    client = auth_client(user, tenant)

    response = client.patch(
        "/api/privacy/", {"data_retention_days": "dużo"}, format="json"
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_usuniecie_rozmowy_kasuje_wszystkie_slady(user, tenant):
    """
    Żądanie usunięcia danych musi objąć też logi wskazujące rozmowę przez
    SET_NULL — inaczej treść pytań zostaje w bazie mimo "usuniętej" rozmowy.
    """
    conversation = Conversation.objects.create(tenant=tenant, user_identifier="10.0.0.0")
    ChatMessage.objects.create(conversation=conversation, sender="user", message="Pytanie")
    PromptLog.objects.create(
        tenant=tenant, conversation=conversation, model="test",
        prompt="Pytanie", response="Odpowiedz", source="gpt",
    )
    ChatUsageLog.objects.create(
        tenant=tenant, conversation=conversation, tokens_used=10, model_used="test",
    )
    ContactRequest.objects.create(
        tenant=tenant, conversation=conversation, contact="jan@example.com",
    )

    client = auth_client(user, tenant)
    response = client.delete(f"/api/privacy/conversations/{conversation.session_id}/")

    assert response.status_code == 200
    assert Conversation.objects.filter(pk=conversation.pk).count() == 0
    assert ChatMessage.objects.count() == 0
    assert PromptLog.objects.filter(tenant=tenant).count() == 0
    assert ChatUsageLog.objects.filter(tenant=tenant).count() == 0
    assert ContactRequest.objects.filter(tenant=tenant).count() == 0


@pytest.mark.django_db
def test_nie_mozna_usunac_rozmowy_innego_klienta(user, tenant):
    from .factories import TenantFactory

    obcy = TenantFactory()
    cudza = Conversation.objects.create(tenant=obcy, user_identifier="10.0.0.0")

    client = auth_client(user, tenant)
    response = client.delete(f"/api/privacy/conversations/{cudza.session_id}/")

    assert response.status_code == 404
    assert Conversation.objects.filter(pk=cudza.pk).exists()


@pytest.mark.django_db
def test_widget_dostaje_link_do_polityki_prywatnosci(tenant):
    """Odwiedzający musi być poinformowany o przetwarzaniu w miejscu zbierania danych."""
    tenant.privacy_policy_url = "https://example.com/prywatnosc"
    tenant.save()

    client = APIClient()
    response = client.get("/api/widget-settings/", HTTP_X_API_KEY=str(tenant.api_key))

    assert response.status_code == 200
    assert response.json()["privacy_policy_url"] == "https://example.com/prywatnosc"


@pytest.mark.django_db
def test_rozmowa_z_widgetu_zapisuje_skrocony_adres_ip(tenant, subscribtion, mocker):
    mocker.patch(
        "api.utils.chat_engine.get_openai_response",
        return_value={"content": "Odpowiedź", "tokens": 5},
    )
    import uuid

    client = APIClient()
    response = client.post(
        "/api/widget/chat/",
        {"message": "Pytanie", "conversation_session_id": str(uuid.uuid4())},
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
        REMOTE_ADDR="203.0.113.42",
    )

    assert response.status_code == 200
    conversation = Conversation.objects.get(tenant=tenant)
    assert conversation.user_identifier == "203.0.113.0"
