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
from api.session_tokens import SessionRefreshToken
from chat.models import FAQ, ContactRequest, Conversation
from documents.models import Document, WebsiteSource

pytestmark = pytest.mark.django_db

# Polityki, od najluźniejszej do najciaśniejszej.
PUBLICZNA = "publiczna"  # przed kontem albo z samym kluczem widgetu; własne kontrole w widoku
KONTO = "konto"  # każdy zalogowany, dotyczy wyłącznie własnego konta
CZLONEK = "członek"  # każda rola w firmie, także viewer
PRACOWNIK = "pracownik"  # właściciel i pracownik; viewer 403
WLASCICIEL = "właściciel"  # tylko właściciel

KONTRAKT = {
    # Przed kontem i widget
    ("register", "POST"): PUBLICZNA,
    ("registration-resend", "POST"): PUBLICZNA,
    ("registration-preview", "POST"): PUBLICZNA,
    ("registration-activate", "POST"): PUBLICZNA,
    ("login", "POST"): PUBLICZNA,
    ("login-2fa", "POST"): PUBLICZNA,
    ("token_refresh", "POST"): PUBLICZNA,
    ("logout", "POST"): PUBLICZNA,
    ("password-reset-request", "POST"): PUBLICZNA,
    ("password-reset-preview", "POST"): PUBLICZNA,
    ("password-reset-confirm", "POST"): PUBLICZNA,
    ("accept-invite", "POST"): PUBLICZNA,
    ("invitation-preview", "GET"): PUBLICZNA,
    ("public-pricing", "GET"): PUBLICZNA,
    ("stripe-webhook", "POST"): PUBLICZNA,
    ("widget-settings", "GET"): PUBLICZNA,
    ("widget-faq", "GET"): PUBLICZNA,
    ("widget-chat", "POST"): PUBLICZNA,
    ("widget-chat-stream", "POST"): PUBLICZNA,
    ("widget-contact", "POST"): PUBLICZNA,
    ("widget-feedback", "POST"): PUBLICZNA,
    # Własne konto
    ("me", "GET"): KONTO,
    ("2fa-stan", "GET"): KONTO,
    ("2fa-rozpocznij", "POST"): KONTO,
    ("2fa-potwierdz", "POST"): KONTO,
    ("2fa-wylacz", "POST"): KONTO,
    ("account-sessions", "GET"): KONTO,
    ("password-change", "POST"): KONTO,
    ("revoke-other-sessions", "POST"): KONTO,
    ("revoke-account-session", "POST"): KONTO,
    ("billing-plans", "GET"): KONTO,
    # Odczyt dla każdej roli
    ("analytics", "GET"): CZLONEK,
    ("documents-list", "GET"): CZLONEK,
    ("documents-detail", "GET"): CZLONEK,
    ("documents-download", "GET"): CZLONEK,
    ("document-detail", "GET"): CZLONEK,
    ("document-chunks", "GET"): CZLONEK,
    ("website-sources-list", "GET"): CZLONEK,
    ("website-sources-detail", "GET"): CZLONEK,
    ("faq-list", "GET"): CZLONEK,
    ("faq-detail", "GET"): CZLONEK,
    ("contact-requests-list", "GET"): CZLONEK,
    ("widget-domain-list", "GET"): CZLONEK,
    ("widget-domain-detail", "GET"): CZLONEK,
    ("chat-logs", "GET"): CZLONEK,
    ("widget-settings-mine", "GET"): CZLONEK,
    ("diagnostyka-adres", "GET"): CZLONEK,
    ("diagnostyka-zadania", "GET"): CZLONEK,
    ("tenant-knowledge", "GET"): CZLONEK,
    ("tenant-privacy", "GET"): CZLONEK,
    # Czat testowy nie zużywa limitu planu i nie wchodzi do statystyk, więc
    # sprawdzenie, jak bot odpowiada, mieści się w roli do oglądania.
    ("chat-test", "GET"): CZLONEK,
    ("chat-test", "POST"): CZLONEK,
    ("chat-test", "DELETE"): CZLONEK,
    ("chat-feedback", "POST"): CZLONEK,
    # Zmiany wiedzy, ustawień i danych klientów
    ("chat", "POST"): PRACOWNIK,
    ("chat-export-csv", "GET"): PRACOWNIK,
    ("chat-import-csv", "POST"): PRACOWNIK,
    ("upload-document", "POST"): PRACOWNIK,
    ("documents-detail", "DELETE"): PRACOWNIK,
    ("documents-przelacz-wyszukiwanie", "PATCH"): PRACOWNIK,
    ("website-sources-list", "POST"): PRACOWNIK,
    ("website-sources-detail", "PUT"): PRACOWNIK,
    ("website-sources-detail", "PATCH"): PRACOWNIK,
    ("website-sources-detail", "DELETE"): PRACOWNIK,
    ("website-sources-recrawl", "POST"): PRACOWNIK,
    ("faq-list", "POST"): PRACOWNIK,
    ("faq-detail", "PUT"): PRACOWNIK,
    ("faq-detail", "PATCH"): PRACOWNIK,
    ("faq-detail", "DELETE"): PRACOWNIK,
    ("contact-requests-detail", "PUT"): PRACOWNIK,
    ("contact-requests-detail", "PATCH"): PRACOWNIK,
    ("widget-domain-detail", "DELETE"): PRACOWNIK,
    ("widget-settings-mine", "PATCH"): PRACOWNIK,
    ("tenant-knowledge", "PATCH"): PRACOWNIK,
    ("tenant-privacy", "PATCH"): PRACOWNIK,
    ("conversation-erase", "DELETE"): PRACOWNIK,
    ("users-list", "GET"): PRACOWNIK,
    ("users-detail", "GET"): PRACOWNIK,
    # Zespół, rozliczenia, dziennik
    ("users-list", "POST"): WLASCICIEL,
    ("users-detail", "PUT"): WLASCICIEL,
    ("users-detail", "PATCH"): WLASCICIEL,
    ("users-detail", "DELETE"): WLASCICIEL,
    ("invite-user", "POST"): WLASCICIEL,
    ("list-invitations", "GET"): WLASCICIEL,
    ("invitation-revoke", "DELETE"): WLASCICIEL,
    ("ustawienia-firmy", "GET"): WLASCICIEL,
    ("ustawienia-firmy", "PATCH"): WLASCICIEL,
    ("dziennik-audytowy", "GET"): WLASCICIEL,
    ("dane-rozliczeniowe", "GET"): WLASCICIEL,
    ("dane-rozliczeniowe", "PUT"): WLASCICIEL,
    ("dane-rozliczeniowe", "PATCH"): WLASCICIEL,
    ("api/billing/create-checkout-session/", "POST"): WLASCICIEL,
    ("billing-portal", "POST"): WLASCICIEL,
    ("billing-checkout-status", "GET"): WLASCICIEL,
}

METODY = ("get", "post", "put", "patch", "delete")
ODMOWA = (401, 403)


def _wzorce(wzorce, prefiks=""):
    for wzorzec in wzorce:
        if isinstance(wzorzec, URLResolver):
            yield from _wzorce(wzorzec.url_patterns, prefiks + str(wzorzec.pattern))
        elif isinstance(wzorzec, URLPattern):
            yield prefiks + str(wzorzec.pattern), wzorzec


def trasy_api():
    """(nazwa, METODA) dla każdej trasy /api/, bez wariantów z rozszerzeniem formatu."""
    wynik = set()
    for trasa, wzorzec in _wzorce(get_resolver().url_patterns):
        if not trasa.startswith("api/") or "format" in trasa:
            continue
        nazwa = wzorzec.name or trasa
        widok = wzorzec.callback
        klasa = getattr(widok, "cls", None)
        akcje = getattr(widok, "actions", None)
        if klasa is None:
            # Widok funkcyjny: metody z dekoratora require_http_methods/csrf_exempt
            # nie są czytelne, a jedynym takim widokiem jest webhook Stripe.
            wynik.add((nazwa, "POST"))
            continue
        # Bez HEAD: DRF dokłada go do każdej trasy z GET i obsługuje tym samym
        # kodem, więc osobny wpis w kontrakcie niczego by nie pilnował.
        dozwolone = set(klasa.http_method_names) - {"head", "options", "trace"}
        if akcje:
            metody = [m for m in akcje if m in dozwolone]
        else:
            metody = [m for m in METODY if hasattr(klasa, m) and m in dozwolone]
        wynik.update((nazwa, m.upper()) for m in metody)
    return wynik


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
        "revoke-account-session": {"session_uuid": uuid.uuid4()},
        "conversation-erase": {"session_id": o.rozmowa.session_id},
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
