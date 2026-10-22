"""
Odczyt stanu rozmowy ma własny limit, osobny od pytań do bota (2.32.7).

Widget pyta o stan rozmowy przy otwarciu, zanim pokaże historię z przeglądarki
(2.21.0). Do 2.32.6 ten odczyt liczył się do tego samego limitu odwiedzającego
co pytania do bota (20 na godzinę): kto otworzył widget dwadzieścia razy,
przechodząc między podstronami, przy pierwszym pytaniu dostawał „zbyt wiele
zapytań" (audyt 2026-10, P08). Odczyt stanu nie kosztuje nas modelu - to jedno
zapytanie do bazy - więc ma osobny, hojniejszy licznik.
"""

import uuid
from datetime import date, timedelta
from unittest import mock

import pytest
from rest_framework.test import APIClient

from accounts.models import Subscription, Tenant

ADRES_IP = "198.51.100.4"


@pytest.fixture
def firma(db):
    tenant = Tenant.objects.create(name="Stan rozmowy")
    # Pro, bo limit firmy (500 na minutę) nie może się tu wtrącić: test liczy
    # limit jednego odwiedzającego, a Start zatrzymałby serię już po 60.
    Subscription.objects.create(
        tenant=tenant,
        plan_type="pro",
        is_active=True,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=30),
    )
    return tenant


def stan(klient, tenant, sesja):
    return klient.get(
        f"/api/widget/rozmowa/{sesja}/", HTTP_X_API_KEY=str(tenant.api_key), REMOTE_ADDR=ADRES_IP
    )


def pytanie(klient, tenant, sesja):
    with (
        mock.patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[]),
        mock.patch(
            "api.utils.chat_engine.get_openai_response",
            return_value={"content": "Dzień dobry.", "tokens": 5},
        ),
    ):
        return klient.post(
            "/api/widget/chat/",
            {"message": "Dzień dobry", "conversation_session_id": sesja},
            format="json",
            HTTP_X_API_KEY=str(tenant.api_key),
            REMOTE_ADDR=ADRES_IP,
        )


@pytest.mark.django_db
class TestOsobnyLimitStanu:
    def test_otwieranie_widgetu_nie_zabiera_pytan_do_bota(self, firma, settings):
        settings.LIMIT_ODWIEDZAJACEGO = "20/hour"
        klient = APIClient()
        sesja = str(uuid.uuid4())

        odczyty = [stan(klient, firma, sesja).status_code for _ in range(20)]

        assert odczyty == [204] * 20
        assert pytanie(klient, firma, sesja).status_code == 200

    def test_pytania_do_bota_nie_zabieraja_odczytow_stanu(self, firma, settings):
        settings.LIMIT_ODWIEDZAJACEGO = "1/hour"
        klient = APIClient()
        sesja = str(uuid.uuid4())

        assert pytanie(klient, firma, sesja).status_code == 200
        assert pytanie(klient, firma, sesja).status_code == 429
        assert stan(klient, firma, sesja).status_code == 204

    def test_odczyt_stanu_tez_ma_granice(self, firma):
        """Domyślna stawka, bez nadpisania: 120 odczytów na godzinę."""
        klient = APIClient()
        sesja = str(uuid.uuid4())

        odczyty = [stan(klient, firma, sesja).status_code for _ in range(121)]

        assert odczyty[:120] == [204] * 120
        assert odczyty[120] == 429
