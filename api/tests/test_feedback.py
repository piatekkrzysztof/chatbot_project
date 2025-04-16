import pytest
from rest_framework.test import APIClient
from chat.models import ChatMessage, ChatFeedback, Conversation
from accounts.models import Tenant


@pytest.mark.django_db
def test_feedback_submission_creates_feedback():
    tenant = Tenant.objects.create(name="T", api_key="x")
    conversation = Conversation.objects.create(id="conv1", tenant=tenant)
    message = ChatMessage.objects.create(
        conversation=conversation,
        sender="bot",
        message="To jest odpowiedź"
    )

    client = APIClient()
    res = client.post("/api/chat/feedback/", {
        "message_id": message.id,
        "is_helpful": True
    })

    assert res.status_code == 200
    assert ChatFeedback.objects.count() == 1
    fb = ChatFeedback.objects.first()
    assert fb.message == message
    assert fb.is_helpful is True