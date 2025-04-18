import pytest
from unittest.mock import patch, MagicMock
from accounts.models import Tenant
from chat.models import Conversation
from api.utils.chat_engine import process_chat_message


@pytest.mark.django_db
@patch("api.utils.chat_engine.match_faq_answer")
def test_faq_fallback_used(mock_match_faq):
    mock_match_faq.return_value = "To jest odpowiedź z FAQ."
    tenant = Tenant.objects.create(name="Firma", owner_email="owner@example.com")
    conversation = Conversation.objects.create(id=1, tenant=tenant)

    result = process_chat_message(tenant, conversation, "Jak założyć konto?")
    assert result["response"] == "To jest odpowiedź z FAQ."
    assert result["source"] == "faq"


@pytest.mark.django_db
@patch("api.utils.chat_engine.get_openai_response")
@patch("api.utils.chat_engine.query_similar_chunks_pgvector")
def test_rag_fallback_used(mock_query_chunks, mock_openai_response):
    mock_query_chunks.return_value = [
        MagicMock(content="To jest tekst z dokumentu 1."),
        MagicMock(content="To jest tekst z dokumentu 2.")
    ]
    mock_openai_response.return_value = {
        "content": "To jest odpowiedź z dokumentu.",
        "tokens": 123,
        "model": "gpt-3.5-turbo"
    }

    tenant = Tenant.objects.create(name="Firma", owner_email="owner@example.com")
    conversation = Conversation.objects.create(id=2, tenant=tenant)

    result = process_chat_message(tenant, conversation, "Co zawiera dokument?")
    assert result["response"] == "To jest odpowiedź z dokumentu."
    assert result["source"] == "document"


@pytest.mark.django_db
@patch("api.utils.chat_engine.build_prompt")
@patch("api.utils.chat_engine.get_openai_response")
@patch("api.utils.chat_engine.query_similar_chunks_pgvector")
@patch("api.utils.chat_engine.match_faq_answer")
def test_gpt_fallback_used(mock_faq, mock_chunks, mock_gpt, mock_prompt):
    mock_faq.return_value = None
    mock_chunks.return_value = []
    mock_prompt.return_value = "Zbudowany prompt GPT"
    mock_gpt.return_value = {
        "content": "To jest odpowiedź z GPT.",
        "tokens": 77,
        "model": "gpt-3.5-turbo"
    }

    tenant = Tenant.objects.create(name="Firma", owner_email="owner@example.com")
    conversation = Conversation.objects.create(id=3, tenant=tenant)

    result = process_chat_message(tenant, conversation, "Opowiedz mi dowcip")
    assert result["response"] == "To jest odpowiedź z GPT."
    assert result["source"] == "gpt"


@pytest.mark.django_db
def test_manual_regulamin_response():
    tenant = Tenant.objects.create(
        name="Firma X", regulamin="To jest regulamin.", owner_email="owner@example.com"
    )
    conversation = Conversation.objects.create(id=4, tenant=tenant)

    result = process_chat_message(tenant, conversation, "Regulamin")
    assert result["response"] == "To jest regulamin."
    assert result["source"] == "manual"
