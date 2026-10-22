"""
Publiczny formularz kontaktu: długość treści i limit jednego odwiedzającego (2.32.5).

Do 2.32.4 formularz miał wyłącznie limit firmy (w planie Start 60 zgłoszeń
na minutę), a pole „Sprawa" nie miało górnej granicy. Każde zgłoszenie to mail
do właściciela wysłany z naszego konta pocztowego. Ktoś z samym publicznym
kluczem widgetu zalewał więc skrzynkę klienta, zużywał wspólny limit wysyłki,
z którego wychodzą też aktywacje kont i resety haseł, i zapisywał w bazie
wiadomości po dwa i pół megabajta (audyt 2026-10, P03).
"""

import uuid
from datetime import date, timedelta
from unittest import mock

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from accounts.models import Subscription, Tenant
from chat.models import ContactRequest

ADRES = "/api/widget/contact/"


@pytest.fixture
def firma(db):
    tenant = Tenant.objects.create(name="Formularz", owner_email="wlasciciel@example.com")
    Subscription.objects.create(
        tenant=tenant,
        plan_type="start",
        is_active=True,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=30),
    )
    return tenant


@pytest.fixture
def zlecenia():
    with mock.patch("api.views.contact.enqueue") as zlecenie:
        yield zlecenie


def zglos(tenant, adres_ip="203.0.113.10", **dane):
    return APIClient().post(
        ADRES,
        {"contact": "odwiedzajacy@example.com", "message": "Proszę o telefon", **dane},
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
        REMOTE_ADDR=adres_ip,
    )


@pytest.mark.django_db
class TestDlugoscTresci:
    def test_tresc_dluzsza_niz_pytanie_czatu_jest_odrzucana(self, firma, zlecenia):
        odpowiedz = zglos(firma, message="x" * (settings.MAX_WIADOMOSC_ZNAKOW + 1))

        assert odpowiedz.status_code == 400
        assert "message" in odpowiedz.json()
        assert not ContactRequest.objects.exists()
        assert zlecenia.call_count == 0

    def test_tresc_na_granicy_jest_przyjmowana(self, firma, zlecenia):
        odpowiedz = zglos(firma, message="x" * settings.MAX_WIADOMOSC_ZNAKOW)

        assert odpowiedz.status_code == 201
        assert len(ContactRequest.objects.get().message) == settings.MAX_WIADOMOSC_ZNAKOW


@pytest.mark.django_db
class TestLimitOdwiedzajacego:
    def test_ponad_limit_jeden_adres_dostaje_429_i_nie_wysyla_maila(self, firma, zlecenia):
        """Domyślna stawka, bez nadpisania: pięć zgłoszeń na godzinę."""
        kody = [zglos(firma).status_code for _ in range(5)]
        szoste = zglos(firma)

        assert kody == [201] * 5
        assert szoste.status_code == 429
        assert int(szoste["Retry-After"]) > 0
        assert ContactRequest.objects.count() == 5
        assert zlecenia.call_count == 5

    def test_inny_adres_i_inna_firma_licza_osobno(self, firma, zlecenia, settings):
        settings.LIMIT_KONTAKTU_ODWIEDZAJACEGO = "1/hour"
        druga = Tenant.objects.create(name="Druga firma")
        Subscription.objects.create(
            tenant=druga,
            plan_type="start",
            is_active=True,
            start_date=date.today() - timedelta(days=1),
            end_date=date.today() + timedelta(days=30),
        )

        assert zglos(firma).status_code == 201
        assert zglos(firma).status_code == 429
        assert zglos(firma, adres_ip="203.0.113.11").status_code == 201
        assert zglos(druga).status_code == 201

    def test_zgloszenie_kontaktu_nie_zabiera_pytan_do_bota(self, firma, zlecenia, settings):
        """Osobny licznik: kontakt i czat jednego odwiedzającego nie dzielą limitu."""
        settings.LIMIT_ODWIEDZAJACEGO = "1/hour"
        settings.LIMIT_KONTAKTU_ODWIEDZAJACEGO = "1/hour"

        assert zglos(firma).status_code == 201

        with (
            mock.patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[]),
            mock.patch(
                "api.utils.chat_engine.get_openai_response",
                return_value={"content": "Oddzwonimy jutro.", "tokens": 5},
            ),
        ):
            czat = APIClient().post(
                "/api/widget/chat/",
                {"message": "Kiedy oddzwonicie?", "conversation_session_id": str(uuid.uuid4())},
                format="json",
                HTTP_X_API_KEY=str(firma.api_key),
                REMOTE_ADDR="203.0.113.10",
            )

        assert czat.status_code == 200
