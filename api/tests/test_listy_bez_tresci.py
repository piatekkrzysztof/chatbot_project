"""
Ekrany panelu nie wczytują całej treści dokumentów ani odpowiedzi bota (audyt 2026-10, P10).

Lista dokumentów pokazuje 500 pierwszych znaków, ekran Stan liczy długość
treści, a lista luk na pulpicie potrzebuje pytania i daty. Wszystkie trzy
ciągnęły z bazy pełne kolumny: treść dokumentu (do 2 mln znaków każda, strona
listy ma 50 pozycji) i pełne odpowiedzi bota. Na instancji z 512 MiB i czterema
wątkami kilka odświeżeń naraz przy dużej bazie wiedzy to setki megabajtów.
Teraz kroi i mierzy baza.
"""

import re
from datetime import date, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from accounts.models import CustomUser, Subscription, Tenant
from api.session_tokens import SessionRefreshToken
from chat.models import ZRODLO_BRAK_WIEDZY, Conversation, PromptLog
from chat.raport_luk import luki_w_wiedzy
from documents.models import Document

#: Kolumna treści wybrana wprost. Wewnątrz funkcji - SUBSTRING czy LENGTH -
#: stoi po nawiasie i wtedy baza oddaje wycinek albo liczbę, nie całość.
TRESC = re.compile(r'(?<!\()"documents_document"\."content"')


def kolumny(sql):
    """Część SELECT zapytania - to, co baza oddaje do Pythona."""
    return sql.split(" FROM ", 1)[0]


@pytest.fixture
def firma(db):
    tenant = Tenant.objects.create(name="Duża wiedza")
    Subscription.objects.create(
        tenant=tenant,
        plan_type="pro",
        is_active=True,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=30),
    )
    return tenant


@pytest.fixture
def klient(firma):
    wlasciciel = CustomUser.objects.create_user(
        username="wlasciciel-listy", email="w@example.com", tenant=firma, role="owner"
    )
    klient = APIClient()
    klient.credentials(
        HTTP_AUTHORIZATION=f"Bearer {SessionRefreshToken.for_user(wlasciciel).access_token}"
    )
    return klient


def zapytania_o_tresc(zapytania):
    return [q["sql"] for q in zapytania.captured_queries if TRESC.search(kolumny(q["sql"]))]


@pytest.mark.django_db
class TestListaDokumentow:
    def test_lista_nie_ciagnie_pelnej_tresci(self, firma, klient):
        Document.objects.create(tenant=firma, name="cennik", content="x" * 2000)

        with CaptureQueriesContext(connection) as zapytania:
            odpowiedz = klient.get("/api/documents/")

        assert odpowiedz.status_code == 200
        assert zapytania_o_tresc(zapytania) == []

    def test_podglad_to_nadal_500_pierwszych_znakow(self, firma, klient):
        Document.objects.create(tenant=firma, name="cennik", content="ą" * 400 + "b" * 400)

        wynik = klient.get("/api/documents/").json()["results"][0]

        assert wynik["preview"] == "ą" * 400 + "b" * 100

    def test_pusta_tresc_to_pusty_podglad(self, firma, klient):
        Document.objects.create(tenant=firma, name="pusty", content="")

        assert klient.get("/api/documents/").json()["results"][0]["preview"] == ""

    def test_jeden_dokument_i_przelaczenie_tez_bez_tresci(self, firma, klient):
        dokument = Document.objects.create(tenant=firma, name="cennik", content="x" * 2000)

        with CaptureQueriesContext(connection) as zapytania:
            szczegoly = klient.get(f"/api/documents/{dokument.pk}/")
            przelaczony = klient.patch(
                f"/api/documents/{dokument.pk}/wyszukiwanie/",
                {"uzywaj_w_wyszukiwaniu": False},
                format="json",
            )

        assert szczegoly.json()["preview"] == "x" * 500
        assert przelaczony.json()["uzywaj_w_wyszukiwaniu"] is False
        assert zapytania_o_tresc(zapytania) == []
        dokument.refresh_from_db()
        assert dokument.content == "x" * 2000


@pytest.mark.django_db
class TestStanSystemu:
    def test_stan_liczy_dlugosc_w_bazie(self, firma, klient):
        Document.objects.create(
            tenant=firma, name="strona", content="x" * 100, znakow_na_stronie=1000
        )

        with CaptureQueriesContext(connection) as zapytania:
            dane = klient.get("/api/diagnostyka/zadania/").json()

        assert zapytania_o_tresc(zapytania) == []
        assert dane["baza_wiedzy"]["niepelne"] == [{"nazwa": "strona", "udzial_procent": 10}]


@pytest.mark.django_db
class TestLukiWWiedzy:
    def test_luki_nie_czytaja_odpowiedzi_bota(self, firma):
        rozmowa = Conversation.objects.create(tenant=firma, user_identifier="gosc", source="widget")
        for _ in range(3):
            PromptLog.objects.create(
                tenant=firma,
                conversation=rozmowa,
                prompt="Czy robicie torty weselne?",
                response="Nie mam tej informacji. " * 200,
                source=ZRODLO_BRAK_WIEDZY,
            )

        with CaptureQueriesContext(connection) as zapytania:
            luki = luki_w_wiedzy(firma)

        assert luki[0]["pytanie"] == "Czy robicie torty weselne?"
        assert luki[0]["ile"] == 3
        assert not [
            q
            for q in zapytania.captured_queries
            if '"chat_promptlog"."response"' in kolumny(q["sql"])
        ]
