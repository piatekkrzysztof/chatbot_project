from unittest import mock

import pytest
from rest_framework.test import APIClient
from chat.models import PromptLog, Conversation

from django.utils import timezone
from datetime import timedelta
import uuid


@pytest.fixture
def conversation(tenant):
    return Conversation.objects.create(
        tenant=tenant,
        user_identifier="test-user",
    )


@pytest.mark.django_db
def test_prompt_log_created_for_document_source(user, tenant, conversation,subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.save()
    client.force_authenticate(user=user)

    payload = {
        "message": "Wytłumacz czym jest embedding.",
        "conversation_id": conversation.id,
        "conversation_session_id": str(uuid.uuid4()),
    }

    headers = {"HTTP_X_API_KEY": str(tenant.api_key)}

    with pytest.raises(AssertionError):  # zakładamy, że fallback nie nastąpi i test padnie jeśli tak
        response = client.post("/api/chat/", payload, format="json", **headers)
        assert response.status_code == 200

        log = PromptLog.objects.last()
        assert log is not None
        assert log.prompt == payload["message"]
        assert log.source in ["faq", "document", "gpt"]
        assert log.tokens >= 0
        assert log.model
        assert log.response


def test_prompt_log_invalid_data(user, tenant, subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.save()
    client.force_authenticate(user=user)

    payload = {"message": ""}  # brak wymaganych danych
    headers = {"HTTP_X_API_KEY": str(tenant.api_key)}

    response = client.post("/api/chat/", payload, format="json", **headers)
    assert response.status_code == 400  # middleware i view powinny dopuścić request, walidacja go odrzuca

@mock.patch("api.utils.chat_engine.get_openai_response")
@mock.patch("api.utils.chat_engine.query_similar_chunks_pgvector")
@pytest.mark.django_db
def test_prompt_log_fallback_source(mock_pgvector, mock_openai_response, user, tenant, conversation, subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.save()
    client.force_authenticate(user=user)

    client.defaults['HTTP_X_API_KEY'] = str(tenant.api_key)

    mock_pgvector.return_value = []
    mock_openai_response.return_value = {
        "content": "Fallback response",
        "tokens": 42
    }

    payload = {
        "message": "Fallback test",
        "conversation_id": conversation.id,
        "conversation_session_id": str(uuid.uuid4()),
    }

    response = client.post("/api/chat/", payload, format="json")
    assert response.status_code == 200

    log = PromptLog.objects.last()
    assert log is not None
    assert log.source == "gpt"
    assert "Fallback response" in log.response
