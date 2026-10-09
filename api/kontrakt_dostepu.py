"""
Kontrakt dostępu do API: polityka każdej trasy i metody.

Źródło prawdy dla dwóch rzeczy. Test `api/tests/test_kontrakt_dostepu.py`
wysyła z każdą tożsamością prawdziwe żądania i pilnuje, że nowa trasa bez
wpisu zatrzymuje CI. Polecenie `macierz_dostepu` buduje z tego czytelną
tabelę „kto co może" (docs/macierz-dostepu.md, F01).

Dopóki słownik żył w pliku testu, tabela dla ludzi musiałaby być osobną
kopią - i rozjechałaby się z testem przy pierwszej nowej trasie.
"""

from django.urls import URLPattern, URLResolver, get_resolver

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
    ("invitation-resend", "POST"): PUBLICZNA,
    ("public-pricing", "GET"): PUBLICZNA,
    ("stripe-webhook", "POST"): PUBLICZNA,
    ("widget-settings", "GET"): PUBLICZNA,
    ("widget-faq", "GET"): PUBLICZNA,
    ("widget-chat", "POST"): PUBLICZNA,
    ("widget-chat-stream", "POST"): PUBLICZNA,
    ("widget-contact", "POST"): PUBLICZNA,
    ("widget-feedback", "POST"): PUBLICZNA,
    ("widget-conversation-status", "GET"): PUBLICZNA,
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
    ("documents-uzycie", "GET"): CZLONEK,
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
    return set(sciezki_tras())


def sciezki_tras():
    """{(nazwa, METODA): wzorzec ścieżki} - to samo co trasy_api, z adresem."""
    wynik = {}
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
            wynik[(nazwa, "POST")] = trasa
            continue
        # Bez HEAD: DRF dokłada go do każdej trasy z GET i obsługuje tym samym
        # kodem, więc osobny wpis w kontrakcie niczego by nie pilnował.
        dozwolone = set(klasa.http_method_names) - {"head", "options", "trace"}
        if akcje:
            metody = [m for m in akcje if m in dozwolone]
        else:
            metody = [m for m in METODY if hasattr(klasa, m) and m in dozwolone]
        wynik.update({(nazwa, m.upper()): trasa for m in metody})
    return wynik
