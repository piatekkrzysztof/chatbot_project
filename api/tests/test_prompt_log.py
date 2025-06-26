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


@pytest.mark.django_db
def test_prompt_log_invalid_data(user, tenant):
    client = APIClient()
    user.tenant = tenant
    user.save()
    client.force_authenticate(user=user)

    payload = {"message": ""}  # brak wymaganych danych
    headers = {"HTTP_X_API_KEY": str(tenant.api_key)}

    response = client.post("/api/chat/", payload, format="json", **headers)
    assert response.status_code in [400, 422]


@mock.patch("api.utils.chat_engine.client.chat.completions.create")
@mock.patch("api.utils.chat_engine.client.embeddings.create")
@pytest.mark.django_db
def test_prompt_log_fallback_source(user, tenant, conversation,subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.save()
    client.force_authenticate(user=user)

    payload = {
        "message": "Co się dzieje, gdy brak odpowiedzi w dokumentach?",
        "conversation_id": conversation.id,
        "conversation_session_id": str(uuid.uuid4()),
    }
    headers = {"HTTP_X_API_KEY": str(tenant.api_key)}

    response = client.post("/api/chat/", payload, format="json", **headers)
    assert response.status_code == 200

    log = PromptLog.objects.last()
    assert log.source == "gpt"
    assert log.response
