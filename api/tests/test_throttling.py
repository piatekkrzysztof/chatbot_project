import pytest
import uuid
from unittest import mock
from rest_framework.test import APIClient
from django.core.cache import cache
from rest_framework.test import APIRequestFactory
from rest_framework.throttling import SimpleRateThrottle
from api.throttles import APIKeyRateThrottle, BaseSubscriptionThrottle
from types import SimpleNamespace

cache.clear()


@mock.patch("api.utils.chat_engine.get_openai_response")
@mock.patch("api.utils.chat_engine.query_similar_chunks_pgvector")
@pytest.mark.django_db
def test_chat_throttling_enforces_limit(mock_pgvector, mock_openai_response, user, tenant, conversation, subscribtion):
    client = APIClient()
    subscribtion.plan_type = "free"
    user.tenant = tenant
    user.save()
    client.force_authenticate(user=user)

    client.defaults["HTTP_X_API_KEY"] = str(tenant.api_key)

    mock_pgvector.return_value = []
    mock_openai_response.return_value = {
        "content": "OK",
        "tokens": 10,
    }

    payload = {
        "message": "test",
        "conversation_id": conversation.id,
        "conversation_session_id": str(conversation.session_id),
    }

    # Wyślij 20 żądań (limit globalny)
    for _ in range(20):
        response = client.post("/api/chat/", payload, format="json")
        print(response.status_code, response.data)
        assert response.status_code != 429, f"Unexpected throttling on {_ + 1} request"

    # 21. żądanie powinno zostać odrzucone

    response = client.post("/api/chat/", payload, format="json")
    print(response.status_code, response.data)
    assert response.status_code == 429, "Throttling not enforced after limit exceeded"


@pytest.mark.parametrize("plan,expected_rate", [
    ("free", "20/min"),
    ("pro", "100/min"),
    ("enterprise", "500/min"),
    (None, "20/min"),
])
def test_get_rate_by_plan(plan, expected_rate):
    class DummyThrottle(BaseSubscriptionThrottle):
        def get_plan_rate(self, plan):
            return {
                "free": "20/min",
                "pro": "100/min",
                "enterprise": "500/min",
            }.get(plan, "20/min")

    throttle = DummyThrottle()
    throttle.request = SimpleNamespace(subscription=SimpleNamespace(plan_type=plan))
    assert throttle.get_rate() == expected_rate


@pytest.mark.django_db
def test_cache_key_generation(tenant,user):
    client=APIClient()
    user.tenant = tenant
    user.save()
    client.force_authenticate(user=user)

    factory = APIRequestFactory()
    request = factory.get("/api/chat/", HTTP_X_API_KEY=str(tenant.api_key))
    throttle = APIKeyRateThrottle()
    key = throttle.get_cache_key(request, None)
    assert key.startswith("throttle_chat_tenant-")


