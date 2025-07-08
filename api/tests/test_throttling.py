import pytest
import uuid
from unittest import mock
from rest_framework.test import APIClient
from django.core.cache import cache

cache.clear()


@mock.patch("api.utils.chat_engine.get_openai_response")
@mock.patch("api.utils.chat_engine.query_similar_chunks_pgvector")
@pytest.mark.django_db
def test_chat_throttling_enforces_limit(mock_pgvector, mock_openai_response, user, tenant, conversation, subscribtion):
    client = APIClient()
    subscribtion.plan_type = "free"
    user.tenant = tenant
    user.save()
    client.force_authenticate(user=user)

    client.defaults["HTTP_X_API_KEY"] = str(tenant.api_key)

    mock_pgvector.return_value = []
    mock_openai_response.return_value = {
        "content": "OK",
        "tokens": 10,
    }

    payload = {
        "message": "test",
        "conversation_id": conversation.id,
        "conversation_session_id": str(conversation.session_id),
    }

    # Wyślij 20 żądań (limit globalny)
    for _ in range(20):
        response = client.post("/api/chat/", payload, format="json")
        print(response.status_code, response.data)
        assert response.status_code != 429, f"Unexpected throttling on {_ + 1} request"

    # 21. żądanie powinno zostać odrzucone

    response = client.post("/api/chat/", payload, format="json")
    print(response.status_code, response.data)
    assert response.status_code == 429, "Throttling not enforced after limit exceeded"
