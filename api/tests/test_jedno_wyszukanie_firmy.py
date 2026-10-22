"""
Ścieżki czatu wyszukują firmę po kluczu raz, nie dwa razy (audyt 2026-10, P22).

TenantMiddleware ustala firmę z klucza widgetu i sprawdza jego zgodność
z kontem, a zaraz po nim SubscriptionMiddleware szukał tej samej firmy po tym
samym kluczu od nowa - jedno zbędne zapytanie przy każdej wiadomości widgetu.
"""

import uuid
from datetime import date, timedelta
from unittest import mock

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from accounts.models import Subscription, Tenant


@pytest.fixture
def firma(db):
    tenant = Tenant.objects.create(name="Jedno wyszukanie")
    Subscription.objects.create(
        tenant=tenant,
        plan_type="start",
        is_active=True,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=30),
    )
    return tenant


def wyszukania_po_kluczu(zapytania):
    return [q for q in zapytania.captured_queries if '"accounts_tenant"."api_key" =' in q["sql"]]


@pytest.mark.django_db
def test_wiadomosc_widgetu_szuka_firmy_po_kluczu_raz(firma):
    with (
        CaptureQueriesContext(connection) as zapytania,
        mock.patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[]),
        mock.patch(
            "api.utils.chat_engine.get_openai_response",
            return_value={"content": "Dzień dobry.", "tokens": 5},
        ),
    ):
        odpowiedz = APIClient().post(
            "/api/widget/chat/",
            {"message": "Dzień dobry", "conversation_session_id": str(uuid.uuid4())},
            format="json",
            HTTP_X_API_KEY=str(firma.api_key),
        )

    assert odpowiedz.status_code == 200
    assert len(wyszukania_po_kluczu(zapytania)) == 1


@pytest.mark.django_db
def test_wygasla_subskrypcja_nadal_odmawia(firma):
    Subscription.objects.filter(tenant=firma).update(end_date=date.today() - timedelta(days=1))

    odpowiedz = APIClient().post(
        "/api/widget/chat/",
        {"message": "Dzień dobry", "conversation_session_id": str(uuid.uuid4())},
        format="json",
        HTTP_X_API_KEY=str(firma.api_key),
    )

    assert odpowiedz.status_code == 403
    assert odpowiedz.json()["kod"] == "czat_niedostepny"


@pytest.mark.django_db
def test_brak_klucza_nadal_odmawia():
    odpowiedz = APIClient().post(
        "/api/widget/chat/",
        {"message": "Dzień dobry", "conversation_session_id": str(uuid.uuid4())},
        format="json",
    )

    assert odpowiedz.status_code == 401
