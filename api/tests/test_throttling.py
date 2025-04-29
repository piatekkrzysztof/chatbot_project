import pytest
from rest_framework.test import APIClient
from accounts.models import Tenant
from chat.models import Conversation

@pytest.mark.django_db
def test_chat_throttling_enforces_limit(settings):
    # Ustaw niski próg na potrzeby testu
    settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["chat"] = "3/min"

    client = APIClient()
    tenant = Tenant.objects.create(name="Firma", api_key="api123", owner_email="x@example.com")
    conv = Conversation.objects.create(id=99, tenant=tenant)

    headers = {"HTTP_X_API_KEY": tenant.api_key}
    payload = {
        "message": "Czy możesz mi pomóc?",
        "conversation_id": str(conv.id)
    }

    url = "/api/chat/"


    for i in range(3):
        res = client.post(url, payload, **headers)
        assert res.status_code != 429, f"Unexpected throttling on attempt {i+1}"

    # 4. powinno już być zablokowane
    res = client.post(url, payload, **headers)
    assert res.status_code == 429
    assert "Request was throttled" in res.data["detail"]
