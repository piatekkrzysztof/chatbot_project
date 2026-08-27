import uuid
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from accounts.models import Tenant, Subscription


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name="WidgetTenant", owner_email="widget@example.com")


@pytest.fixture
def subscribtion(db, tenant):
    return Subscription.objects.create(
        tenant=tenant,
        is_active=True,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=30),
    )


@pytest.mark.django_db
def test_widget_chat_success_without_auth(tenant, subscribtion):
    client = APIClient()
    payload = {
        "message": "Jakie są Wasze godziny otwarcia?",
        "conversation_id": "widget-1",
        "conversation_session_id": str(uuid.uuid4()),
    }

    with patch(
        "api.views.widget.process_chat_message",
        return_value={
            "response": "Jesteśmy dostępni 9-17.",
            "source": "gpt",
            "tokens": 0,
        },
    ):
        response = client.post(
            "/api/widget/chat/",
            payload,
            format="json",
            HTTP_X_API_KEY=str(tenant.api_key),
        )

    assert response.status_code == 200
    assert response.data["response"] == "Jesteśmy dostępni 9-17."


@pytest.mark.django_db
def test_widget_chat_invalid_api_key():
    client = APIClient()
    payload = {
        "message": "Test",
        "conversation_id": "x",
        "conversation_session_id": str(uuid.uuid4()),
    }
    response = client.post(
        "/api/widget/chat/", payload, format="json", HTTP_X_API_KEY=str(uuid.uuid4())
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_widget_chat_enforces_subscription_limit(tenant, subscribtion):
    client = APIClient()
    subscribtion.message_limit = 3
    subscribtion.save()

    # billable=True odwzorowuje udaną odpowiedź modelu — bez tego pola widok
    # uznaje wywołanie za nieudane i słusznie nie nalicza wiadomości
    with patch(
        "api.views.widget.process_chat_message",
        return_value={
            "response": "ok",
            "source": "gpt",
            "tokens": 0,
            "billable": True,
        },
    ):
        for _ in range(3):
            res = client.post(
                "/api/widget/chat/",
                {
                    "message": "test",
                    "conversation_id": "x",
                    "conversation_session_id": str(uuid.uuid4()),
                },
                format="json",
                HTTP_X_API_KEY=str(tenant.api_key),
            )
            assert res.status_code == 200

        res = client.post(
            "/api/widget/chat/",
            {
                "message": "test",
                "conversation_id": "x",
                "conversation_session_id": str(uuid.uuid4()),
            },
            format="json",
            HTTP_X_API_KEY=str(tenant.api_key),
        )
        assert res.status_code == 429
