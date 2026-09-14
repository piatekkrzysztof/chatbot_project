"""
F16, część 1: stała liczba zapytań na listach panelu i stronicowanie list, które rosną.

Pomiar z 14.09.2026 (3 i 30 obiektów każdego rodzaju): lista dokumentów robiła
dwa dodatkowe zapytania na dokument (63 zapytania przy 30 dokumentach), historia
rozmów jedno na wpis, a historia i zapytania kontaktowe szły w całości - widok
historii miał klasę stronicowania bez rozmiaru strony, więc nie stronicował.
"""

from datetime import date, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from accounts.models import (
    CustomUser,
    InvitationToken,
    Subscription,
    Tenant,
    WidgetDomain,
    WpisDziennika,
)
from chat.models import FAQ, ChatFeedback, ChatMessage, ContactRequest, Conversation, PromptLog
from documents.models import Document, DocumentChunk, WebsiteSource
from documents.wymiar import WYMIAR_WEKTORA

LISTY_PANELU = [
    "/api/documents/",
    "/api/users/",
    "/api/website-sources/",
    "/api/faq/",
    "/api/contact-requests/",
    "/api/widget-domains/",
    "/api/accounts/invitations/list/",
    "/api/chat/logs/",
    "/api/accounts/dziennik/",
    "/api/knowledge/",
    "/api/analytics/",
    "/api/chat/export/",
]


def firma_z_wlascicielem(nazwa):
    tenant = Tenant.objects.create(name=nazwa, owner_email=f"szef-{nazwa}@firma.pl")
    Subscription.objects.create(
        tenant=tenant,
        plan_type="pro",
        is_active=True,
        message_limit=25_000,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=30),
    )
    wlasciciel = CustomUser.objects.create_user(
        username=f"szef-{nazwa}", email=f"szef-{nazwa}@firma.pl", password="x", tenant=tenant
    )
    wlasciciel.role = "owner"
    wlasciciel.save()
    return tenant, wlasciciel


def klient(tenant, uzytkownik):
    wynik = APIClient()
    wynik.force_authenticate(user=uzytkownik)
    wynik.credentials(HTTP_X_API_KEY=str(tenant.api_key))
    return wynik


def zasiej(tenant, wlasciciel, ile):
    for i in range(ile):
        dokument = Document.objects.create(
            tenant=tenant, name=f"dok {i}", content="treść", processed=True
        )
        for _ in range(2):
            DocumentChunk.objects.create(
                document=dokument, content="fragment", embedding=[0.0] * WYMIAR_WEKTORA
            )
        WebsiteSource.objects.create(tenant=tenant, url=f"https://s{tenant.id}-{i}.pl/")
        FAQ.objects.create(tenant=tenant, question=f"pytanie {i}", answer="odpowiedź")
        rozmowa = Conversation.objects.create(tenant=tenant, user_identifier=f"u{i}")
        ChatMessage.objects.create(conversation=rozmowa, sender="user", message="pytanie")
        odpowiedz = ChatMessage.objects.create(
            conversation=rozmowa, sender="bot", message=f"odpowiedź {i}"
        )
        ChatFeedback.objects.create(message=odpowiedz, is_helpful=i % 2 == 0)
        PromptLog.objects.create(
            tenant=tenant,
            conversation=rozmowa,
            model="gpt-4o-mini",
            prompt="p",
            source="faq",
            response=f"odpowiedź {i}",
        )
        ContactRequest.objects.create(
            tenant=tenant, conversation=rozmowa, contact=f"k{i}@klient.pl"
        )
        InvitationToken.objects.create(tenant=tenant, email=f"z{i}-{tenant.id}@firma.pl")
        WidgetDomain.objects.create(tenant=tenant, host=f"w{i}-{tenant.id}.pl")
        WpisDziennika.objects.create(
            tenant=tenant, uzytkownik=wlasciciel, metoda="POST", sciezka="/api/faq/", status=201
        )
        pracownik = CustomUser.objects.create_user(
            username=f"p{i}-{tenant.id}",
            email=f"p{i}-{tenant.id}@firma.pl",
            password="x",
            tenant=tenant,
        )
        pracownik.role = "employee"
        pracownik.save()


def liczba_zapytan(klient_api, adres):
    with CaptureQueriesContext(connection) as zapytania:
        odpowiedz = klient_api.get(adres)
    assert odpowiedz.status_code == 200, (adres, odpowiedz.status_code)
    return len(zapytania)


@pytest.mark.django_db
def test_listy_panelu_maja_stala_liczbe_zapytan():
    """
    Ta sama liczba zapytań przy 3 i przy 30 obiektach. Wzrost oznacza zapytanie
    w pętli po wierszach - koszt, który rośnie razem z klientem.
    """
    mala, wlasciciel_malej = firma_z_wlascicielem("mala")
    duza, wlasciciel_duzej = firma_z_wlascicielem("duza")
    zasiej(mala, wlasciciel_malej, 3)
    zasiej(duza, wlasciciel_duzej, 30)

    rosnace = {}
    for adres in LISTY_PANELU:
        przy_malej = liczba_zapytan(klient(mala, wlasciciel_malej), adres)
        przy_duzej = liczba_zapytan(klient(duza, wlasciciel_duzej), adres)
        if przy_duzej != przy_malej:
            rosnace[adres] = (przy_malej, przy_duzej)

    assert rosnace == {}


@pytest.fixture
def firma(db):
    return firma_z_wlascicielem("stronicowana")


def rozmowa_z_logami(tenant, ile):
    rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="gosc")
    PromptLog.objects.bulk_create(
        PromptLog(
            tenant=tenant,
            conversation=rozmowa,
            model="gpt-4o-mini",
            prompt=f"pytanie {i}",
            source="faq",
            response=f"odpowiedź {i}",
        )
        for i in range(ile)
    )
    return rozmowa


@pytest.mark.django_db
class TestHistoriiRozmow:
    def test_historia_jest_stronicowana(self, firma):
        tenant, wlasciciel = firma
        rozmowa_z_logami(tenant, 55)

        pierwsza = klient(tenant, wlasciciel).get("/api/chat/logs/").json()
        druga = klient(tenant, wlasciciel).get("/api/chat/logs/?page=2").json()

        assert pierwsza["count"] == 55
        assert len(pierwsza["results"]) == 50
        assert pierwsza["next"]
        assert len(druga["results"]) == 5
        # Najnowsze na pierwszej stronie
        assert pierwsza["results"][0]["prompt"] == "pytanie 54"

    def test_rozmiar_strony_ma_gorny_limit(self, firma):
        tenant, wlasciciel = firma
        rozmowa_z_logami(tenant, 210)

        dane = klient(tenant, wlasciciel).get("/api/chat/logs/?rozmiar=1000").json()

        assert len(dane["results"]) == 200

    def test_ocena_zostaje_przy_wpisie(self, firma):
        tenant, wlasciciel = firma
        rozmowa = rozmowa_z_logami(tenant, 2)
        oceniona = ChatMessage.objects.create(
            conversation=rozmowa, sender="bot", message="odpowiedź 1"
        )
        ChatFeedback.objects.create(message=oceniona, is_helpful=False)

        wpisy = klient(tenant, wlasciciel).get("/api/chat/logs/").json()["results"]

        assert {w["response"]: w["is_helpful"] for w in wpisy} == {
            "odpowiedź 1": False,
            "odpowiedź 0": None,
        }

    def test_filtr_ocen_nie_siega_do_innych_firm(self, firma):
        # Identyczna odpowiedź oceniona w innej firmie trafiała na listę
        # „niepomocnych", choć tutaj nikt jej nie ocenił.
        tenant, wlasciciel = firma
        rozmowa_z_logami(tenant, 1)
        inna, _ = firma_z_wlascicielem("inna")
        cudza_rozmowa = Conversation.objects.create(tenant=inna, user_identifier="obcy")
        cudza = ChatMessage.objects.create(
            conversation=cudza_rozmowa, sender="bot", message="odpowiedź 0"
        )
        ChatFeedback.objects.create(message=cudza, is_helpful=False)

        dane = klient(tenant, wlasciciel).get("/api/chat/logs/?is_helpful=false").json()

        assert dane["results"] == []


@pytest.mark.django_db
class TestZapytanKontaktowych:
    def test_zapytania_sa_stronicowane_od_najnowszych(self, firma):
        tenant, wlasciciel = firma
        for i in range(55):
            ContactRequest.objects.create(tenant=tenant, contact=f"k{i}@klient.pl")

        dane = klient(tenant, wlasciciel).get("/api/contact-requests/").json()

        assert dane["count"] == 55
        assert len(dane["results"]) == 50
        assert dane["results"][0]["contact"] == "k54@klient.pl"

    def test_licznik_nieobsluzonych_obejmuje_wszystkie_strony(self, firma):
        tenant, wlasciciel = firma
        for i in range(55):
            ContactRequest.objects.create(tenant=tenant, contact=f"k{i}@klient.pl", handled=i < 3)
        inna, _ = firma_z_wlascicielem("obca")
        ContactRequest.objects.create(tenant=inna, contact="cudzy@klient.pl")

        dane = klient(tenant, wlasciciel).get("/api/contact-requests/").json()

        assert dane["nieobsluzone"] == 52


@pytest.mark.django_db
def test_status_dokumentu_bez_zmian_po_dolaczeniu_liczby_fragmentow(firma):
    tenant, wlasciciel = firma
    z_fragmentami = Document.objects.create(tenant=tenant, name="a", processed=True)
    DocumentChunk.objects.create(
        document=z_fragmentami, content="x", embedding=[0.0] * WYMIAR_WEKTORA
    )
    Document.objects.create(tenant=tenant, name="b", processed=True)
    Document.objects.create(tenant=tenant, name="c", processed=False)

    dokumenty = klient(tenant, wlasciciel).get("/api/documents/").json()

    assert {d["name"]: (d["chunk_count"], d["status"]) for d in dokumenty} == {
        "a": (1, "ready"),
        "b": (0, "processed_no_chunks"),
        "c": (0, "processing"),
    }
