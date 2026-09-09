"""Retencja ma zachować świeże dane, także przy nieaktualnej dacie rozmowy."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from chat.models import (
    ChatFeedback,
    ChatMessage,
    ChatUsageLog,
    ContactRequest,
    Conversation,
    PromptLog,
)
from chat.retention import purge_tenant


def expired_conversation(tenant, now):
    tenant.data_retention_days = 30
    tenant.save(update_fields=["data_retention_days"])
    conversation = Conversation.objects.create(tenant=tenant, user_identifier="synthetic-visitor")
    message = ChatMessage.objects.create(conversation=conversation, sender="user", message="Old")
    old = now - timedelta(days=45)
    Conversation.objects.filter(pk=conversation.pk).update(last_message_at=old)
    ChatMessage.objects.filter(pk=message.pk).update(timestamp=old)
    return conversation, message


@pytest.mark.django_db
def test_new_message_preserves_old_conversation_even_with_stale_cached_date(tenant):
    now = timezone.now()
    conversation, old = expired_conversation(tenant, now)
    new = ChatMessage.objects.create(conversation=conversation, sender="user", message="Fresh")
    # Reprezentuje dane zapisane przed naprawą, także przez import/bulk_create.
    Conversation.objects.filter(pk=conversation.pk).update(last_message_at=now - timedelta(days=45))

    removed = purge_tenant(tenant, now=now)

    assert Conversation.objects.filter(pk=conversation.pk).exists()
    assert set(conversation.messages.values_list("pk", flat=True)) == {old.pk, new.pk}
    assert removed.get("Conversation", 0) == 0


@pytest.mark.django_db
@pytest.mark.parametrize("sender", ["user", "bot", "system"])
def test_message_updates_conversation_activity(tenant, sender):
    now = timezone.now()
    conversation, _ = expired_conversation(tenant, now)

    message = ChatMessage.objects.create(conversation=conversation, sender=sender, message="Fresh")

    conversation.refresh_from_db()
    assert conversation.last_message_at >= message.timestamp


@pytest.mark.django_db
def test_message_on_cutoff_is_preserved(tenant):
    now = timezone.now()
    conversation, message = expired_conversation(tenant, now)
    ChatMessage.objects.filter(pk=message.pk).update(timestamp=now - timedelta(days=30))

    purge_tenant(tenant, now=now)

    assert ChatMessage.objects.filter(pk=message.pk).exists()


@pytest.mark.django_db
def test_expired_conversation_removes_messages_and_feedback(tenant):
    now = timezone.now()
    conversation, message = expired_conversation(tenant, now)
    feedback = ChatFeedback.objects.create(message=message, is_helpful=True)

    removed = purge_tenant(tenant, now=now)

    assert not Conversation.objects.filter(pk=conversation.pk).exists()
    assert not ChatFeedback.objects.filter(pk=feedback.pk).exists()
    assert removed == {"ChatFeedback": 1, "ChatMessage": 1, "Conversation": 1}


@pytest.mark.django_db
def test_expired_empty_conversation_is_removed(tenant):
    now = timezone.now()
    conversation, message = expired_conversation(tenant, now)
    message.delete()

    purge_tenant(tenant, now=now)

    assert not Conversation.objects.filter(pk=conversation.pk).exists()


@pytest.mark.django_db
def test_editing_old_message_does_not_move_activity_backwards(tenant):
    now = timezone.now()
    conversation, old = expired_conversation(tenant, now)
    ChatMessage.objects.create(conversation=conversation, sender="user", message="Fresh")
    conversation.refresh_from_db()
    last_activity = conversation.last_message_at
    old.refresh_from_db()

    old.message = "Edited old message"
    old.save(update_fields=["message"])

    conversation.refresh_from_db()
    assert conversation.last_message_at == last_activity


@pytest.mark.django_db
def test_failed_message_write_does_not_extend_retention(tenant):
    now = timezone.now()
    conversation, _ = expired_conversation(tenant, now)
    conversation.refresh_from_db()
    last_activity = conversation.last_message_at

    with pytest.raises(RuntimeError), transaction.atomic():
        ChatMessage.objects.create(conversation=conversation, sender="user", message="Rollback")
        raise RuntimeError("synthetic rollback")

    conversation.refresh_from_db()
    assert conversation.last_message_at == last_activity
    assert not conversation.messages.filter(message="Rollback").exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("model", "fields"),
    [
        (PromptLog, {"model": "test", "prompt": "Synthetic", "source": "faq"}),
        (ChatUsageLog, {"tokens_used": 1}),
        (ContactRequest, {"contact": "synthetic@example.test"}),
    ],
)
def test_active_conversation_does_not_prevent_log_and_contact_retention(tenant, model, fields):
    now = timezone.now()
    conversation, _ = expired_conversation(tenant, now)
    ChatMessage.objects.create(conversation=conversation, sender="user", message="Fresh")
    old = model.objects.create(tenant=tenant, conversation=conversation, **fields)
    fresh = model.objects.create(tenant=tenant, conversation=conversation, **fields)
    model.objects.filter(pk=old.pk).update(created_at=now - timedelta(days=45))

    purge_tenant(tenant, now=now)

    assert Conversation.objects.filter(pk=conversation.pk).exists()
    assert not model.objects.filter(pk=old.pk).exists()
    assert model.objects.filter(pk=fresh.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_retention_skips_conversation_with_uncommitted_message(tenant):
    if connection.vendor != "postgresql":
        pytest.skip("Ten kontrakt wymaga blokad PostgreSQL")
    now = timezone.now()
    conversation, _ = expired_conversation(tenant, now)
    written = Event()
    release = Event()

    def writer():
        close_old_connections()
        try:
            with transaction.atomic():
                message = ChatMessage.objects.create(
                    conversation_id=conversation.pk, sender="user", message="In progress"
                )
                written.set()
                assert release.wait(10), "Retencja nie zwolniła piszącej transakcji"
            return message.pk
        finally:
            connection.close()

    def purge():
        close_old_connections()
        try:
            return purge_tenant(tenant, now=now)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        saving = pool.submit(writer)
        try:
            assert written.wait(10)
            cleaning = pool.submit(purge)
            removed = cleaning.result(timeout=5)
            assert removed.get("Conversation", 0) == 0
        finally:
            release.set()
        message_id = saving.result(timeout=10)

    assert ChatMessage.objects.filter(pk=message_id).exists()
    assert Conversation.objects.filter(pk=conversation.pk).exists()
