import pytest
from unittest.mock import patch, MagicMock
from openai import OpenAIError

from accounts.models import Tenant
from chat.models import Conversation, ChatMessage, FAQ
from api.utils.chat_engine import (
    process_chat_message,
    get_openai_response,
    build_chat_messages,
    build_history_messages,
)


def make_chunk(content, doc_name, source_url=""):
    chunk = MagicMock()
    chunk.content = content
    chunk.document.name = doc_name
    # Pusty adres to nie brak danych, tylko domyślny stan wgranego pliku —
    # linkujemy wyłącznie treści, które i tak są publiczne
    chunk.document.source_url = source_url
    return chunk


@pytest.mark.django_db
@patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[])
def test_regulamin_lands_in_system_prompt(mock_chunks):
    tenant = Tenant.objects.create(
        name="Firma", owner_email="x@example.com", regulamin="Mój regulamin."
    )
    conversation = Conversation.objects.create(tenant=tenant)

    messages, _, _ = build_chat_messages(tenant, conversation, "jaki jest regulamin?")

    assert messages[0]["role"] == "system"
    assert "Mój regulamin." in messages[0]["content"]


@pytest.mark.django_db
@patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[])
def test_faq_lands_in_system_prompt(mock_chunks):
    tenant = Tenant.objects.create(name="Firma", owner_email="x@example.com")
    FAQ.objects.create(tenant=tenant, question="Godziny otwarcia?", answer="9-17")
    conversation = Conversation.objects.create(tenant=tenant)

    messages, _, faqs = build_chat_messages(tenant, conversation, "kiedy otwarte?")

    assert "Godziny otwarcia?" in messages[0]["content"]
    assert "9-17" in messages[0]["content"]
    assert len(faqs) == 1


@pytest.mark.django_db
def test_history_is_passed_in_order():
    tenant = Tenant.objects.create(name="Firma", owner_email="x@example.com")
    conversation = Conversation.objects.create(tenant=tenant)
    ChatMessage.objects.create(conversation=conversation, sender="user", message="Cześć")
    ChatMessage.objects.create(conversation=conversation, sender="bot", message="Dzień dobry")
    ChatMessage.objects.create(conversation=conversation, sender="user", message="Ile kosztuje?")

    history = build_history_messages(conversation)

    assert history == [
        {"role": "user", "content": "Cześć"},
        {"role": "assistant", "content": "Dzień dobry"},
        {"role": "user", "content": "Ile kosztuje?"},
    ]


@pytest.mark.django_db
@patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[])
@patch("api.utils.chat_engine.get_openai_response")
def test_current_message_is_last(mock_gpt, mock_chunks):
    mock_gpt.return_value = {"content": "ok", "tokens": 1}
    tenant = Tenant.objects.create(name="Firma", owner_email="x@example.com")
    conversation = Conversation.objects.create(tenant=tenant)

    process_chat_message(tenant, conversation, "Nowe pytanie")

    messages = mock_gpt.call_args.args[0]
    assert messages[-1] == {"role": "user", "content": "Nowe pytanie"}


@pytest.mark.django_db
@patch("api.utils.chat_engine.query_similar_chunks_pgvector")
@patch("api.utils.chat_engine.get_openai_response")
def test_document_source_returns_citations(mock_gpt, mock_chunks):
    mock_chunks.return_value = [
        make_chunk("fragment 1", "cennik.pdf"),
        make_chunk("fragment 2", "cennik.pdf"),
        make_chunk("fragment 3", "regulamin.pdf"),
    ]
    mock_gpt.return_value = {"content": "Odpowiedź RAG", "tokens": 123}

    tenant = Tenant.objects.create(name="Firma", owner_email="x@example.com")
    conversation = Conversation.objects.create(tenant=tenant)

    result = process_chat_message(tenant, conversation, "Pytanie o dokumenty")

    assert result["response"] == "Odpowiedź RAG"
    assert result["tokens"] == 123
    assert result["source"] == "document"
    assert result["sources"] == [
        {"name": "cennik.pdf", "url": ""},
        {"name": "regulamin.pdf", "url": ""},
    ]


@pytest.mark.django_db
@patch("api.utils.chat_engine.query_similar_chunks_pgvector")
@patch("api.utils.chat_engine.get_openai_response")
def test_strona_www_dostaje_klikalny_adres(mock_gpt, mock_chunks):
    """
    Treść zaimportowana z witryny klienta jest publiczna, więc bot może podać
    do niej link. Odwiedzający może sprawdzić odpowiedź u źródła.
    """
    mock_chunks.return_value = [
        make_chunk("fragment", "Cennik usług", "https://firma.pl/cennik"),
    ]
    mock_gpt.return_value = {"content": "Odpowiedź", "tokens": 10}

    tenant = Tenant.objects.create(name="Firma", owner_email="x@example.com")
    conversation = Conversation.objects.create(tenant=tenant)

    result = process_chat_message(tenant, conversation, "Ile kosztuje?")

    assert result["sources"] == [
        {"name": "Cennik usług", "url": "https://firma.pl/cennik"},
    ]


@pytest.mark.django_db
@patch("api.utils.chat_engine.query_similar_chunks_pgvector")
@patch("api.utils.chat_engine.get_openai_response")
def test_wgrany_plik_nie_dostaje_adresu(mock_gpt, mock_chunks):
    """
    Sedno decyzji o prywatności. Link do wgranego dokumentu oznaczałby, że każdy
    odwiedzający pobierze cennik wewnętrzny czy procedury, które klient wgrał
    wyłącznie po to, żeby bot z nich korzystał.
    """
    mock_chunks.return_value = [make_chunk("fragment", "procedury_wewnetrzne.pdf")]
    mock_gpt.return_value = {"content": "Odpowiedź", "tokens": 10}

    tenant = Tenant.objects.create(name="Firma", owner_email="x@example.com")
    conversation = Conversation.objects.create(tenant=tenant)

    result = process_chat_message(tenant, conversation, "Jak wygląda procedura?")

    assert result["sources"][0]["url"] == ""


@pytest.mark.django_db
@patch("api.utils.chat_engine.query_similar_chunks_pgvector", side_effect=Exception("Błąd"))
@patch("api.utils.chat_engine.get_openai_response")
def test_gpt_fallback_when_retrieval_fails(mock_gpt, mock_chunks):
    mock_gpt.return_value = {"content": "Odpowiedź GPT fallback", "tokens": 99}

    tenant = Tenant.objects.create(name="Firma", owner_email="x@example.com")
    conversation = Conversation.objects.create(tenant=tenant)

    result = process_chat_message(tenant, conversation, "Pytanie ogólne")

    assert result["response"] == "Odpowiedź GPT fallback"
    assert result["source"] == "gpt"
    assert result["sources"] == []


@pytest.mark.django_db
@patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[])
@patch("api.utils.chat_engine.get_openai_response", side_effect=Exception("boom"))
def test_model_error_returns_friendly_message(mock_gpt, mock_chunks):
    from api.utils.chat_engine import FALLBACK_MESSAGE

    tenant = Tenant.objects.create(name="Firma", owner_email="x@example.com")
    conversation = Conversation.objects.create(tenant=tenant)

    result = process_chat_message(tenant, conversation, "Pytanie")

    assert result["response"] == FALLBACK_MESSAGE
    assert result["tokens"] == 0


@pytest.mark.django_db
@patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[])
@patch("api.utils.chat_engine.get_openai_response")
def test_unrelated_question_is_not_counted_as_faq_coverage(mock_gpt, mock_chunks):
    """
    Istnienie wpisów FAQ nie może samo w sobie oznaczać pokrycia — inaczej
    raport luk w wiedzy byłby pusty u każdego klienta, który dodał jedno FAQ.
    """
    mock_gpt.return_value = {"content": "Nie wiem.", "tokens": 5}
    tenant = Tenant.objects.create(name="Firma", owner_email="x@example.com")
    FAQ.objects.create(tenant=tenant, question="Czy naprawiacie rowery elektryczne?", answer="Tak")
    conversation = Conversation.objects.create(tenant=tenant)

    result = process_chat_message(
        tenant, conversation, "Czy organizujecie wycieczki po Bieszczadach?"
    )

    assert result["source"] == "gpt"


@pytest.mark.django_db
@patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[])
@patch("api.utils.chat_engine.get_openai_response")
def test_matching_question_is_counted_as_faq_coverage(mock_gpt, mock_chunks):
    mock_gpt.return_value = {"content": "Tak.", "tokens": 5}
    tenant = Tenant.objects.create(name="Firma", owner_email="x@example.com")
    FAQ.objects.create(tenant=tenant, question="Czy naprawiacie rowery elektryczne?", answer="Tak")
    conversation = Conversation.objects.create(tenant=tenant)

    result = process_chat_message(tenant, conversation, "Czy naprawiacie rowery elektryczne?")

    assert result["source"] == "faq"


# Podmieniamy get_client, a nie klasę OpenAI: to jedyny szew, przez który
# testowany kod sięga po klienta, i to jego pilnuje bezpiecznik w conftest.
@patch("api.utils.chat_engine.get_client")
def test_get_openai_response_success(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="Hi"))], usage=MagicMock(total_tokens=12)
    )

    res = get_openai_response([{"role": "user", "content": "Hello"}])
    assert res["content"] == "Hi"
    assert res["tokens"] == 12


@patch("api.utils.chat_engine.get_client")
def test_get_openai_response_handles_failure(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.chat.completions.create.side_effect = OpenAIError("API error")

    with pytest.raises(OpenAIError):
        get_openai_response([{"role": "user", "content": "Hello"}])
