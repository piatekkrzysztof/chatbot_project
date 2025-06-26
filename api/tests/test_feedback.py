import pytest
from rest_framework.test import APIClient
from chat.models import ChatMessage, ChatFeedback, Conversation
from accounts.models import Tenant


@pytest.mark.django_db
def test_submit_valid_feedback(user, tenant, subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.role = "owner"
    user.save()
    tenant.save()
    client.force_authenticate(user=user)
    conv = Conversation.objects.create(id=1, tenant=tenant)

    message = ChatMessage.objects.create(
        conversation=conv,
        sender="bot",
        message="Odpowiedź bota"
    )

    res = client.post("/api/chat/feedback/", {"message_id": message.id, "is_helpful": True},HTTP_X_API_KEY=str(tenant.api_key))

    assert res.status_code == 200
    assert ChatFeedback.objects.filter(message=message, is_helpful=True).exists()


@pytest.mark.django_db
def test_feedback_missing_message_id(user, tenant, subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.role = "owner"
    user.save()
    tenant.save()
    client.force_authenticate(user=user)
    res = client.post("/api/chat/feedback/", {"is_helpful": True},HTTP_X_API_KEY=str(tenant.api_key))
    assert res.status_code == 400
    assert "message_id" in res.json()


@pytest.mark.django_db
def test_feedback_missing_is_helpful(user, tenant, subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.role = "owner"
    user.save()
    tenant.save()
    client.force_authenticate(user=user)
    conv = Conversation.objects.create(id=1, tenant=tenant)
    msg = ChatMessage.objects.create(conversation=conv, sender="bot", message="hej")


    res = client.post("/api/chat/feedback/", {"message_id": msg.id},HTTP_X_API_KEY=str(tenant.api_key))
    assert res.status_code == 400
    assert "is_helpful" in res.json()


@pytest.mark.django_db
def test_feedback_nonexistent_message(user, tenant, subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.role = "owner"
    user.save()
    tenant.save()
    client.force_authenticate(user=user)
    res = client.post("/api/chat/feedback/", {"message_id": 999, "is_helpful": True},HTTP_X_API_KEY=str(tenant.api_key))
    assert res.status_code == 400
    assert "message_id" in res.json()


@pytest.mark.django_db
def test_feedback_rejected_for_user_message(user, tenant, subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.role = "owner"
    user.save()
    tenant.save()
    client.force_authenticate(user=user)
    conv = Conversation.objects.create(id=1, tenant=tenant)

    user_msg = ChatMessage.objects.create(
        conversation=conv,
        sender="user",
        message="To nie jest bot"
    )

    res = client.post("/api/chat/feedback/", {"message_id": user_msg.id, "is_helpful": True},HTTP_X_API_KEY=str(tenant.api_key))
    assert res.status_code == 400
    assert "message_id" in res.json()


@pytest.mark.django_db
def test_feedback_overwrites_previous(user, tenant, subscribtion):
    client = APIClient()
    user.tenant = tenant
    user.role = "owner"
    user.save()
    tenant.save()
    client.force_authenticate(user=user)
    conv = Conversation.objects.create(id=1, tenant=tenant)
    msg = ChatMessage.objects.create(conversation=conv, sender="bot", message="Hej")

    ChatFeedback.objects.create(message=msg, is_helpful=False)

    res = client.post("/api/chat/feedback/", {"message_id": msg.id, "is_helpful": True},HTTP_X_API_KEY=str(tenant.api_key))
    assert res.status_code == 200

    feedback = ChatFeedback.objects.get(message=msg)
    assert feedback.is_helpful is True
