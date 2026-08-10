import pytest
import uuid
from unittest import mock
from rest_framework.test import APIClient
from django.core.cache import cache
from rest_framework.test import APIRequestFactory
from rest_framework.throttling import SimpleRateThrottle
from accounts.plans import PLANS, rate_for
from api.throttles import APIKeyRateThrottle, BaseSubscriptionThrottle
from types import SimpleNamespace

cache.clear()


@mock.patch("api.utils.chat_engine.get_openai_response")
@mock.patch("api.utils.chat_engine.query_similar_chunks_pgvector")
@pytest.mark.django_db
def test_chat_throttling_enforces_limit(mock_pgvector, mock_openai_response, user, tenant, conversation, subscribtion):
    client = APIClient()
    # Stawka pochodzi z katalogu planów — test nie może jej powtarzać własną
    # liczbą, bo wtedy czerwieni się przy każdej zmianie cennika zamiast
    # sprawdzać, czy limit w ogóle działa.
    # Zapis jest konieczny: throttle czyta subskrypcję z bazy, więc bez niego
    # test sprawdzałby plan z fikstury, a nie ten, który ustawia.
    subscribtion.plan_type = "start"
    subscribtion.save()
    limit = PLANS["start"].rate_per_minute
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

    for numer in range(limit):
        response = client.post("/api/chat/", payload, format="json")
        assert response.status_code != 429, f"Limit zadziałał za wcześnie, przy {numer + 1}"

    response = client.post("/api/chat/", payload, format="json")
    assert response.status_code == 429, f"Limit {limit}/min nie zadziałał po przekroczeniu"


@pytest.mark.parametrize("plan,expected_rate", [
    (kod, rate_for(kod)) for kod in PLANS
] + [(None, rate_for(None))])
def test_get_rate_by_plan(plan, expected_rate):
    """
    Sprawdzamy prawdziwy throttle, nie atrapę. Wcześniej test definiował własną
    klasę z powtórzoną mapą stawek — przechodził więc również wtedy, gdy
    produkcyjna mapa rozjechała się z cennikiem, co dokładnie się stało: plan
    "basic" nie pasował do niczego i dostawał limit darmowy.
    """
    throttle = APIKeyRateThrottle()
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


