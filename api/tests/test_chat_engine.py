import pytest
from unittest.mock import patch, MagicMock
from accounts.models import Tenant
from chat.models import Conversation
from api.utils.chat_engine import process_chat_message
from unittest.mock import patch
from api.utils.chat_engine import get_openai_response
from openai import OpenAIError


@pytest.mark.django_db
def test_regulamin_fallback_used():
    tenant = Tenant.objects.create(name="Firma", owner_email="x@example.com", regulamin="Mój regulamin.")
    conversation = Conversation.objects.create(id=1, tenant=tenant)

    result = process_chat_message(tenant, conversation, "regulamin")
    assert result["response"] == "Mój regulamin."


@pytest.mark.django_db
@patch("api.utils.chat_engine.query_similar_chunks_pgvector")
@patch("api.utils.chat_engine.get_openai_response")
def test_rag_fallback_used(mock_gpt, mock_chunks):
    mock_chunks.return_value = [MagicMock(content="fragment 1"), MagicMock(content="fragment 2")]
    mock_gpt.return_value = {"content": "Odpowiedź RAG", "tokens": 123}

    tenant = Tenant.objects.create(name="Firma", owner_email="x@example.com")
    conversation = Conversation.objects.create(id=2, tenant=tenant)

    result = process_chat_message(tenant, conversation, "Pytanie o dokumenty")
    assert result["response"] == "Odpowiedź RAG"
    assert result["tokens"] == 123
    assert result["source"] == "document"


@pytest.mark.django_db
@patch("api.utils.chat_engine.query_similar_chunks_pgvector", side_effect=Exception("Błąd"))
@patch("api.utils.chat_engine.get_openai_response")
def test_gpt_fallback_used(mock_gpt, mock_chunks):
    mock_gpt.return_value = {"content": "Odpowiedź GPT fallback", "tokens": 99}

    tenant = Tenant.objects.create(name="Firma", owner_email="x@example.com")
    conversation = Conversation.objects.create(id=3, tenant=tenant)

    result = process_chat_message(tenant, conversation, "Pytanie ogólne")
    assert result["response"] == "Odpowiedź GPT fallback"
    assert result["tokens"] == 99
    assert result["source"] == "gpt"


@patch("api.utils.chat_engine.OpenAI")
def test_get_openai_response_success(mock_openai):
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message={"content": "Hi"})],
        usage=MagicMock(total_tokens=12)
    )

    res = get_openai_response("Hello")
    assert res["content"] == "Hi"
    assert res["tokens"] == 12


@patch("api.utils.chat_engine.OpenAI")
def test_get_openai_response_handles_failure(mock_openai):
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    mock_client.chat.completions.create.side_effect = OpenAIError("API error")

    try:
        get_openai_response("Hello")
    except OpenAIError:
        assert True  # wyjątek złapany poprawnie
    else:
        assert False, "OpenAIError powinien zostać rzucony"
