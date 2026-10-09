"""
Macierz dostępu (F01): czytelna tabela „kto co może", zbudowana z kontraktu.

Kontrakt (`api/kontrakt_dostepu.py`) mówi to samo co tabela, ale językiem
testu: jedna polityka na trasę i metodę. Tabela rozpisuje politykę na pięć
tożsamości, z którymi ktoś faktycznie przychodzi do API. Test pilnuje, że
docs/macierz-dostepu.md jest równy temu, co buduje ta funkcja - tabela nie
może się zestarzeć, bo kontrakt nie może.

    python manage.py macierz_dostepu --zapisz
"""

import re

from api.kontrakt_dostepu import (
    CZLONEK,
    KONTO,
    KONTRAKT,
    PRACOWNIK,
    PUBLICZNA,
    WLASCICIEL,
    sciezki_tras,
)

SCIEZKA_DOKUMENTU = "docs/macierz-dostepu.md"

#: Kto przechodzi kontrolę uprawnień przy danej polityce. Kolumny w kolejności
#: tabeli: anonim, sam klucz widgetu, podgląd (viewer), pracownik, właściciel.
KTO_PRZECHODZI = {
    PUBLICZNA: (True, True, True, True, True),
    KONTO: (False, False, True, True, True),
    CZLONEK: (False, False, True, True, True),
    PRACOWNIK: (False, False, False, True, True),
    WLASCICIEL: (False, False, False, False, True),
}

KOLUMNY = ("Anonim", "Sam klucz widgetu", "Podgląd", "Pracownik", "Właściciel")

#: Grupy tras w kolejności, w jakiej czyta się panel.
GRUPY = (
    (
        "Logowanie, rejestracja i hasło",
        (
            "accounts/login",
            "accounts/register",
            "accounts/registration",
            "accounts/password",
            "accounts/token",
            "accounts/logout",
            "accounts/accept-invite",
            "accounts/invit",
        ),
    ),
    ("Widget na stronie klienta", ("widget/",)),
    ("Konto, bezpieczeństwo i firma", ("accounts/",)),
    ("Wiedza bota", ("documents", "knowledge", "faq", "website-sources")),
    ("Rozmowy, kontakty i prywatność", ("chat", "conversations", "contact", "privacy", "leads")),
    ("Wygląd i witryny widgetu", ("widget-settings", "widget-domains")),
    ("Zespół", ("users",)),
    ("Pulpit i diagnostyka", ("analytics", "diagnostyka")),
    ("Płatności", ("billing", "stripe", "pricing")),
)

#: Opisy operacji, które w schemacie OpenAPI nie mają krótkiego podsumowania
#: (viewsety routera i kilka widoków konta - ich opis to docstring klasy, np.
#: „Mixin ograniczający queryset…", czyli nic dla czytelnika tej tabeli).
OPISY_UZUPELNIAJACE = {
    ("password-change", "POST"): "Zmiana własnego hasła",
    ("password-reset-request", "POST"): "Prośba o link do resetu hasła",
    ("password-reset-preview", "POST"): "Sprawdzenie linku do resetu hasła",
    ("password-reset-confirm", "POST"): "Ustawienie nowego hasła z linku",
    ("registration-activate", "POST"): "Aktywacja konta z linku w e-mailu",
    ("registration-preview", "POST"): "Sprawdzenie linku aktywacyjnego",
    ("registration-resend", "POST"): "Ponowne wysłanie linku aktywacyjnego",
    ("revoke-account-session", "POST"): "Wylogowanie jednej własnej sesji",
    ("revoke-other-sessions", "POST"): "Wylogowanie pozostałych własnych sesji",
    ("stripe-webhook", "POST"): "Powiadomienie od Stripe (podpisane)",
    ("contact-requests-list", "GET"): "Lista zapytań od odwiedzających",
    ("contact-requests-detail", "PUT"): "Oznaczenie zapytania jako obsłużone",
    ("contact-requests-detail", "PATCH"): "Oznaczenie zapytania jako obsłużone",
    ("documents-list", "GET"): "Lista dokumentów",
    ("documents-detail", "GET"): "Szczegóły dokumentu",
    ("document-detail", "GET"): "Szczegóły dokumentu (trasa przesłonięta przez router)",
    ("documents-download", "GET"): "Pobranie pliku dokumentu",
    ("faq-list", "GET"): "Lista wpisów FAQ",
    ("faq-list", "POST"): "Dodanie wpisu FAQ",
    ("faq-detail", "GET"): "Wpis FAQ",
    ("faq-detail", "PUT"): "Zmiana wpisu FAQ",
    ("faq-detail", "PATCH"): "Zmiana wpisu FAQ",
    ("faq-detail", "DELETE"): "Usunięcie wpisu FAQ",
    ("users-list", "GET"): "Lista osób w zespole",
    ("users-list", "POST"): "Dodanie osoby do zespołu",
    ("users-detail", "GET"): "Osoba w zespole",
    ("users-detail", "PUT"): "Zmiana roli osoby",
    ("users-detail", "PATCH"): "Zmiana roli osoby",
    ("users-detail", "DELETE"): "Usunięcie osoby z zespołu",
    ("website-sources-list", "GET"): "Lista stron WWW w wiedzy",
    ("website-sources-list", "POST"): "Dodanie strony WWW",
    ("website-sources-detail", "GET"): "Strona WWW w wiedzy",
    ("website-sources-detail", "PUT"): "Zmiana strony WWW",
    ("website-sources-detail", "PATCH"): "Zmiana strony WWW",
    ("website-sources-detail", "DELETE"): "Usunięcie strony WWW z wiedzy",
}

_PARAMETR_DJANGO = re.compile(r"<(?:\w+:)?(\w+)>")
_PARAMETR_REGEX = re.compile(r"\(\?P<(\w+)>[^)]*\)")


def _sciezka_openapi(trasa):
    """`api/documents/<int:pk>/` i `api/^documents/(?P<pk>[^/.]+)/$` -> `/api/documents/{pk}/`."""
    trasa = _PARAMETR_REGEX.sub(r"{\1}", trasa)  # najpierw regex: zawiera „<pk>"
    trasa = _PARAMETR_DJANGO.sub(r"{\1}", trasa)
    trasa = trasa.replace("/^", "/").removeprefix("^").removesuffix("$")
    return "/" + trasa.lstrip("/")


def _klucz(sciezka):
    """Schemat nazywa parametr routera `{id}`, Django `{pk}` - porównujemy bez nazw."""
    return re.sub(r"\{\w+\}", "{}", sciezka)


def _opisy():
    """Krótki opis operacji z schematu OpenAPI: {(ścieżka, METODA): opis}."""
    from drf_spectacular.generators import SchemaGenerator

    schemat = SchemaGenerator().get_schema(request=None, public=True)
    return {
        (_klucz(sciezka), metoda.upper()): (operacja.get("summary") or "").strip()
        for sciezka, metody in schemat["paths"].items()
        for metoda, operacja in metody.items()
    }


def _grupa(sciezka):
    bez_prefiksu = sciezka.removeprefix("/api/")
    for numer, (_, prefiksy) in enumerate(GRUPY):
        if bez_prefiksu.startswith(prefiksy):
            return numer
    return len(GRUPY)


def zbuduj_macierz():
    sciezki = sciezki_tras()
    opisy = _opisy()
    wiersze = []
    for (nazwa, metoda), polityka in KONTRAKT.items():
        sciezka = _sciezka_openapi(sciezki[(nazwa, metoda)])
        opis = opisy.get((_klucz(sciezka), metoda)) or OPISY_UZUPELNIAJACE.get((nazwa, metoda), "-")
        wiersze.append((_grupa(sciezka), sciezka, metoda, opis, polityka))
    wiersze.sort(key=lambda w: (w[0], w[1], "GET POST PUT PATCH DELETE".index(w[2])))

    linie = [
        "# Macierz dostępu do API (F01)",
        "",
        "Kto może wywołać którą operację. **Plik generowany** z kontraktu",
        "`api/kontrakt_dostepu.py` poleceniem `python manage.py macierz_dostepu --zapisz`;",
        "test pilnuje, że jest aktualny. Nie edytować ręcznie.",
        "",
        "Każdy wiersz jest sprawdzany prawdziwymi żądaniami w",
        "`api/tests/test_kontrakt_dostepu.py` - opis metody i wyniki są w",
        "[kontrakt-dostepu.md](kontrakt-dostepu.md).",
        "",
        "## Jak czytać",
        "",
        "- **Anonim** - bez logowania i bez klucza.",
        "- **Sam klucz widgetu** - jawny klucz z kodu strony klienta; widzi go każdy odwiedzający.",
        "- **Podgląd**, **Pracownik**, **Właściciel** - role w zespole firmy, z tokenem",
        "  zalogowanego konta i kluczem własnej firmy.",
        "- „tak” przy operacji publicznej znaczy, że kontrola dostępu nie odrzuca - widok",
        "  sprawdza resztę sam (klucz widgetu, podpis Stripe, token z e-maila, limit).",
        "- „tak” przy koncie dotyczy wyłącznie własnego konta zalogowanej osoby.",
        "- Nikt nie sięga danych innej firmy: właściciel firmy B dostaje 403 albo 404",
        "  na każdej operacji z identyfikatorem obiektu firmy A, a token firmy A z kluczem",
        "  firmy B - 403 wszędzie poza operacjami publicznymi i własnym kontem.",
        "",
        f"Operacji: {len(wiersze)}.",
    ]
    nazwy_grup = [g for g, _ in GRUPY] + ["Pozostałe"]
    biezaca = None
    for grupa, sciezka, metoda, opis, polityka in wiersze:
        if grupa != biezaca:
            biezaca = grupa
            linie += [
                "",
                f"## {nazwy_grup[grupa]}",
                "",
                "| Operacja | Opis | " + " | ".join(KOLUMNY) + " |",
                "|---|---|" + "---|" * len(KOLUMNY),
            ]
        komorki = ["tak" if przechodzi else "-" for przechodzi in KTO_PRZECHODZI[polityka]]
        linie.append(f"| `{metoda} {sciezka}` | {opis} | " + " | ".join(komorki) + " |")
    return "\n".join(linie) + "\n"
