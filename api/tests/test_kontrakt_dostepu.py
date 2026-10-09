"""
Pełny negatywny test dostępu - etap 8 roadmapy.

Kategoria ryzyka: DOSTĘP. Dotychczasowe testy granic sprawdzały wybrane
końcówki. Tu każda trasa /api/ i każda jej metoda ma zapisaną politykę, a test
wysyła prawdziwe żądania z każdą tożsamością, której nie wolno przejść:
anonim, sam klucz widgetu, rola za niska, właściciel innej firmy.

Test pierwszy pilnuje, że lista jest kompletna. Nowa końcówka bez wpisu tutaj
zatrzymuje CI - inaczej kontrakt starzałby się po cichu, a luka w nowej
końcówce przechodziłaby przez zielony zestaw testów.

Uprawnienia nie są odczytywane z klas widoków. Akcje viewsetów nadpisują
`permission_classes`, a `get_permissions` bywa zmieniane w metodzie - dlatego
rozstrzyga odpowiedź serwera na realne żądanie, nie deklaracja w kodzie.
"""

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import CustomUser, InvitationToken, Subscription, Tenant, WidgetDomain
from api.kontrakt_dostepu import (
    CZLONEK,
    KONTO,
    KONTRAKT,
    METODY,
    ODMOWA,
    PRACOWNIK,
    PUBLICZNA,
    WLASCICIEL,
    trasy_api,
)
from api.session_tokens import SessionRefreshToken
from chat.models import FAQ, ContactRequest, Conversation
from documents.models import Document, WebsiteSource

pytestmark = pytest.mark.django_db


@pytest.fixture
def swiat():
    a = Tenant.objects.create(name="Firma A", owner_email="a@firma-a.pl")
    b = Tenant.objects.create(name="Firma B", owner_email="b@firma-b.pl")
    for firma in (a, b):
        Subscription.objects.create(
            tenant=firma,
            plan_type="pro",
            is_active=True,
            message_limit=25_000,
            start_date=timezone.now().date() - timedelta(days=1),
            end_date=timezone.now().date() + timedelta(days=30),
        )
    # Bez haseł: token powstaje wprost, a liczenie skrótu hasła dla pięciu kont
    # w każdym z kilkuset przypadków wydłużało test do kilkunastu minut.
    osoby = {
        rola: CustomUser.objects.create_user(
            username=f"a-{rola}", email=f"{rola}@firma-a.pl", tenant=a, role=rola
        )
        for rola in ("owner", "employee", "viewer")
    }
    wlasciciel_b = CustomUser.objects.create_user(
        username="b-owner", email="owner@firma-b.pl", tenant=b, role="owner"
    )
    dokument = Document.objects.create(tenant=a, name="A", content="A", processed=True)
    obiekty = SimpleNamespace(
        dokument=dokument,
        strona=WebsiteSource.objects.create(tenant=a, url="https://firma-a.pl"),
        faq=FAQ.objects.create(tenant=a, question="A?", answer="A."),
        zapytanie=ContactRequest.objects.create(tenant=a, name="Jan", contact="jan@example.com"),
        domena=WidgetDomain.objects.create(tenant=a, host="firma-a.pl"),
        zaproszenie=InvitationToken.objects.create(tenant=a, email="nowy@firma-a.pl"),
        rozmowa=Conversation.objects.create(tenant=a, user_identifier="odwiedzajacy"),
    )
    return SimpleNamespace(a=a, b=b, osoby=osoby, wlasciciel_b=wlasciciel_b, obiekty=obiekty)


def adres(swiat, nazwa):
    o = swiat.obiekty
    argumenty = {
        "documents-detail": {"pk": o.dokument.pk},
        "documents-download": {"pk": o.dokument.pk},
        "documents-przelacz-wyszukiwanie": {"pk": o.dokument.pk},
        "document-detail": {"pk": o.dokument.pk},
        "document-chunks": {"document_id": o.dokument.pk},
        "website-sources-detail": {"pk": o.strona.pk},
        "website-sources-recrawl": {"pk": o.strona.pk},
        "faq-detail": {"pk": o.faq.pk},
        "contact-requests-detail": {"pk": o.zapytanie.pk},
        "widget-domain-detail": {"pk": o.domena.pk},
        "users-detail": {"pk": swiat.osoby["employee"].pk},
        "invitation-revoke": {"pk": o.zaproszenie.pk},
        "invitation-preview": {"token": o.zaproszenie.token},
        "invitation-resend": {"token_wysylki": o.zaproszenie.token_wysylki},
        "revoke-account-session": {"session_uuid": uuid.uuid4()},
        "conversation-erase": {"session_id": o.rozmowa.session_id},
        "widget-conversation-status": {"session_id": o.rozmowa.session_id},
        "billing-checkout-status": {"session_id": "cs_test_a1B2c3D4e5F6g7H8"},
    }.get(nazwa, {})
    if nazwa.startswith("api/"):
        return f"/{nazwa}"
    return reverse(nazwa, kwargs=argumenty)


def z_tokenem(uzytkownik, klucz=None):
    klient = APIClient(HTTP_ORIGIN="https://panel.example.test")
    naglowki = {
        "HTTP_AUTHORIZATION": f"Bearer {SessionRefreshToken.for_user(uzytkownik).access_token}"
    }
    if klucz is not None:
        naglowki["HTTP_X_API_KEY"] = str(klucz)
    klient.credentials(**naglowki)
    return klient


def wyslij(klient, metoda, sciezka):
    return getattr(klient, metoda.lower())(sciezka, {}, format="json")


def wpisy(*polityki):
    return sorted(klucz for klucz, polityka in KONTRAKT.items() if polityka in polityki)


def test_kazda_trasa_api_ma_zapisana_polityke():
    trasy = trasy_api()

    bez_polityki = sorted(trasy - set(KONTRAKT))
    nieistniejace = sorted(set(KONTRAKT) - trasy)

    assert not bez_polityki, f"Trasy bez polityki dostępu w KONTRAKT: {bez_polityki}"
    assert not nieistniejace, f"Wpisy KONTRAKT dla nieistniejących tras: {nieistniejace}"


@pytest.mark.parametrize("nazwa,metoda", wpisy(KONTO, CZLONEK, PRACOWNIK, WLASCICIEL))
def test_anonim_nie_przechodzi(swiat, nazwa, metoda):
    odpowiedz = wyslij(APIClient(), metoda, adres(swiat, nazwa))

    assert odpowiedz.status_code in ODMOWA


@pytest.mark.parametrize("nazwa,metoda", wpisy(KONTO, CZLONEK, PRACOWNIK, WLASCICIEL))
def test_sam_klucz_widgetu_nie_otwiera_panelu(swiat, nazwa, metoda):
    # Klucz jest jawny w kodzie strony klienta. Gdyby otwierał choć jedną
    # końcówkę panelu, każdy odwiedzający miałby do niej dostęp.
    klient = APIClient(HTTP_X_API_KEY=str(swiat.a.api_key))

    assert wyslij(klient, metoda, adres(swiat, nazwa)).status_code in ODMOWA


@pytest.mark.parametrize("nazwa,metoda", wpisy(PRACOWNIK, WLASCICIEL))
def test_viewer_nie_przechodzi_powyzej_odczytu(swiat, nazwa, metoda):
    # Z własnym kluczem firmy: to najpełniejsze poprawne żądanie tej roli.
    # Bez klucza część tras odmawia już w middleware (401), więc test nie
    # sprawdzałby wtedy samej roli.
    klient = z_tokenem(swiat.osoby["viewer"], swiat.a.api_key)
    odpowiedz = wyslij(klient, metoda, adres(swiat, nazwa))

    assert odpowiedz.status_code == 403


@pytest.mark.parametrize("nazwa,metoda", wpisy(WLASCICIEL))
def test_pracownik_nie_ma_uprawnien_wlasciciela(swiat, nazwa, metoda):
    klient = z_tokenem(swiat.osoby["employee"], swiat.a.api_key)
    odpowiedz = wyslij(klient, metoda, adres(swiat, nazwa))

    assert odpowiedz.status_code == 403


@pytest.mark.parametrize("nazwa,metoda", wpisy(CZLONEK, PRACOWNIK, WLASCICIEL))
def test_obcy_klucz_przy_wlasnym_tokenie_jest_odrzucany(swiat, nazwa, metoda):
    # JWT firmy A z kluczem firmy B: żądanie nie może ani przejść, ani
    # podmienić firmy na B.
    klient = z_tokenem(swiat.osoby["owner"], swiat.b.api_key)

    assert wyslij(klient, metoda, adres(swiat, nazwa)).status_code == 403


@pytest.mark.parametrize(
    "nazwa,metoda",
    [
        klucz
        for klucz in wpisy(CZLONEK, PRACOWNIK, WLASCICIEL)
        if klucz[0]
        in {
            "documents-detail",
            "documents-download",
            "documents-przelacz-wyszukiwanie",
            "document-detail",
            "document-chunks",
            "website-sources-detail",
            "website-sources-recrawl",
            "faq-detail",
            "contact-requests-detail",
            "widget-domain-detail",
            "users-detail",
            "invitation-revoke",
            "conversation-erase",
        }
    ],
)
def test_wlasciciel_innej_firmy_nie_siega_obiektow_firmy_a(swiat, nazwa, metoda):
    klient = z_tokenem(swiat.wlasciciel_b, swiat.b.api_key)

    assert wyslij(klient, metoda, adres(swiat, nazwa)).status_code in (403, 404)


#: Odczyty, które po przejściu kontroli wołają usługę zewnętrzną: stan zakupu
#: pyta Stripe o sesję, diagnostyka zadań pinguje brokera. Test dostępu nie
#: może zależeć od sieci; ich odmowy sprawdzają testy wyżej, bo kontrola
#: uprawnień zapada przed kodem widoku.
ODCZYTY_Z_SIECIA = {"billing-checkout-status", "diagnostyka-zadania"}


@pytest.mark.parametrize(
    "nazwa,metoda",
    [
        klucz
        for klucz in wpisy(KONTO, CZLONEK, PRACOWNIK, WLASCICIEL)
        if klucz[1] == "GET" and klucz[0] not in ODCZYTY_Z_SIECIA
    ],
)
def test_uprawniony_wlasciciel_przechodzi_kontrole_odczytu(swiat, nazwa, metoda):
    # Kontrola pozytywna. Bez niej wszystkie testy odmowy przeszłyby także
    # wtedy, gdyby środowisko testu odrzucało każde żądanie z innego powodu.
    odpowiedz = wyslij(z_tokenem(swiat.osoby["owner"]), metoda, adres(swiat, nazwa))

    assert odpowiedz.status_code not in (401, 403, 500)
