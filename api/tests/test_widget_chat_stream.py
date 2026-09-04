import json
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from rest_framework.test import APIClient

from accounts.models import Subscription, Tenant
from chat.models import ChatMessage, Conversation, PromptLog


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name="StreamTenant", owner_email="stream@example.com")


@pytest.fixture
def subscribtion(db, tenant):
    return Subscription.objects.create(
        tenant=tenant,
        is_active=True,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=30),
    )


def make_openai_stream(pieces, total_tokens=42):
    """Imituje strumień z OpenAI: kilka fragmentów treści, na końcu zużycie tokenów."""
    events = []
    for piece in pieces:
        delta = MagicMock()
        delta.content = piece
        choice = MagicMock()
        choice.delta = delta
        event = MagicMock()
        event.choices = [choice]
        event.usage = None
        events.append(event)

    final = MagicMock()
    final.choices = []
    final.usage = MagicMock(total_tokens=total_tokens)
    events.append(final)
    return events


def parse_sse(response):
    body = b"".join(response.streaming_content).decode("utf-8")
    return [
        json.loads(line[6:]) for line in body.split("\n\n") if line.strip().startswith("data: ")
    ]


@pytest.mark.django_db
@patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[])
@patch("api.utils.chat_engine.get_client")
def test_stream_returns_deltas_then_done(mock_client, mock_chunks, tenant, subscribtion):
    mock_client.return_value.chat.completions.create.return_value = make_openai_stream(
        ["Dzień ", "dobry", "!"]
    )

    client = APIClient()
    response = client.post(
        "/api/widget/chat/stream/",
        {
            "message": "Cześć",
            "conversation_id": "x",
            "conversation_session_id": str(uuid.uuid4()),
        },
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "text/event-stream"

    events = parse_sse(response)
    deltas = [e for e in events if e["type"] == "delta"]
    done = [e for e in events if e["type"] == "done"]

    assert [d["content"] for d in deltas] == ["Dzień ", "dobry", "!"]
    assert len(done) == 1
    assert done[0]["tokens"] == 42


@pytest.mark.django_db
@patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[])
@patch("api.utils.chat_engine.get_client")
def test_stream_persists_full_answer(mock_client, mock_chunks, tenant, subscribtion):
    mock_client.return_value.chat.completions.create.return_value = make_openai_stream(
        ["Odpowiedź ", "w kawałkach"]
    )

    session_id = str(uuid.uuid4())
    client = APIClient()
    response = client.post(
        "/api/widget/chat/stream/",
        {
            "message": "Pytanie",
            "conversation_id": "x",
            "conversation_session_id": session_id,
        },
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
    )
    parse_sse(response)  # strumień musi zostać skonsumowany, żeby zapis się wykonał

    conversation = Conversation.objects.get(session_id=session_id)
    bot_messages = ChatMessage.objects.filter(conversation=conversation, sender="bot")
    assert bot_messages.count() == 1
    assert bot_messages.first().message == "Odpowiedź w kawałkach"

    log = PromptLog.objects.filter(conversation=conversation).last()
    assert log.prompt == "Pytanie"
    assert log.response == "Odpowiedź w kawałkach"


@pytest.mark.django_db
@patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[])
@patch("api.utils.chat_engine.get_client")
def test_stream_counts_against_message_limit(mock_client, mock_chunks, tenant, subscribtion):
    mock_client.return_value.chat.completions.create.return_value = make_openai_stream(["ok"])

    client = APIClient()
    response = client.post(
        "/api/widget/chat/stream/",
        {
            "message": "Pytanie",
            "conversation_id": "x",
            "conversation_session_id": str(uuid.uuid4()),
        },
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
    )
    # Wiadomość nalicza się dopiero, gdy odwiedzający realnie dostanie treść,
    # więc strumień trzeba skonsumować tak, jak robi to przeglądarka
    b"".join(response.streaming_content)

    subscribtion.refresh_from_db()
    assert subscribtion.current_message_count == 1


@pytest.mark.django_db
def test_stream_rejects_bad_api_key():
    client = APIClient()
    response = client.post(
        "/api/widget/chat/stream/",
        {
            "message": "Pytanie",
            "conversation_id": "x",
            "conversation_session_id": str(uuid.uuid4()),
        },
        format="json",
        HTTP_X_API_KEY=str(uuid.uuid4()),
    )
    assert response.status_code == 401
