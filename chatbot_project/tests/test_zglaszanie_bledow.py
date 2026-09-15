"""
Co z adresu żądania trafia do Sentry.

Kategoria ryzyka: DANE POZA SYSTEMEM. Zdarzenie w Sentry niesie pełny adres
żądania i jego zapytanie. Część naszych adresów ma w ścieżce wartość, która
sama otwiera dostęp albo wskazuje osobę: token zaproszenia do zespołu,
identyfikator rozmowy odwiedzającego, identyfikator sesji płatności. Zapytanie
w adresie niesie z kolei to, czego ktoś szukał w panelu - także e-maile
klientów. Nic z tego nie jest potrzebne do zdiagnozowania błędu, a Sentry to
osobna usługa z własnym dostępem i własnym czasem przechowywania.
"""

from chatbot_project.observability import redact_credentials

TOKEN = "3f1c2a9e-8b7d-4c6e-9f10-2a3b4c5d6e7f"


def test_token_zaproszenia_nie_trafia_do_adresu_ani_nazwy_transakcji():
    event = {
        "request": {"url": f"https://api.example.test/api/accounts/invitations/{TOKEN}/preview/"},
        "transaction": f"/api/accounts/invitations/{TOKEN}/preview/",
    }

    wynik = redact_credentials(event, {})

    assert TOKEN not in str(wynik)
    assert wynik["request"]["url"] == (
        "https://api.example.test/api/accounts/invitations/[uuid]/preview/"
    )
    assert wynik["transaction"] == "/api/accounts/invitations/[uuid]/preview/"


def test_identyfikator_sesji_platnosci_jest_maskowany():
    sesja = "cs_live_a1B2c3D4e5F6g7H8"
    event = {"request": {"url": f"https://api.example.test/api/billing/checkout-session/{sesja}/"}}

    wynik = redact_credentials(event, {})

    assert sesja not in str(wynik)
    assert wynik["request"]["url"].endswith("/checkout-session/[sesja-stripe]/")


def test_zapytanie_w_adresie_nie_trafia_do_zdarzenia():
    event = {
        "request": {
            "url": "https://api.example.test/api/contact-requests/",
            "query_string": "search=jan.kowalski%40example.com",
        }
    }

    wynik = redact_credentials(event, {})

    assert "query_string" not in wynik["request"]
    assert wynik["request"]["url"] == "https://api.example.test/api/contact-requests/"


def test_zwykly_adres_i_nazwa_trasy_zostaja_bez_zmian():
    # Maskowanie ma usuwać sekrety, nie wartość diagnostyczną: numer FAQ
    # i wzorzec trasy mówią, gdzie szukać błędu.
    event = {
        "request": {"url": "https://api.example.test/api/faq/12/", "method": "PATCH"},
        "transaction": "/api/faq/{pk}/",
    }

    wynik = redact_credentials(event, {})

    assert wynik["request"] == {"url": "https://api.example.test/api/faq/12/", "method": "PATCH"}
    assert wynik["transaction"] == "/api/faq/{pk}/"


def test_zdarzenie_bez_zadania_przechodzi_bez_zmian():
    event = {"message": "Zadanie w tle nie powiodło się"}

    assert redact_credentials(event, {}) == {"message": "Zadanie w tle nie powiodło się"}
