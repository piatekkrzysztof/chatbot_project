import pytest
from rest_framework.test import APIClient
from django.test.utils import override_settings
import uuid
from chat.models import Conversation
from unittest import mock

@override_settings(REST_FRAMEWORK={
    "DEFAULT_THROTTLE_CLASSES": [
        "api.throttles.APIKeyRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "chat": "3/min",
    }
})

@pytest.fixture
def conversation(user, tenant):
    return Conversation.objects.create(
        tenant=tenant,
        )

@mock.patch("api.utils.chat_engine.get_openai_response")
@mock.patch("api.utils.chat_engine.query_similar_chunks_pgvector")
@pytest.mark.django_db
def test_chat_throttling_enforces_limit(user, tenant, conversation,subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.save()
    client.force_authenticate(user=user)
    client.defaults['HTTP_X_API_KEY'] = str(tenant.api_key)

    payload = {
        "message": "test",
        "conversation_id": conversation.id,
        "conversation_session_id": str(uuid.uuid4()),
    }

    for _ in range(3):
        response = client.post("/api/chat/", payload, format="json")
        assert response.status_code != 429

    # Czwarta próba powinna zostać zablokowana
    response = client.post("/api/chat/", payload, format="json")
    assert response.status_code == 429
    assert "Throttled" in response.data["detail"]
