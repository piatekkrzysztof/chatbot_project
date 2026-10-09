# Macierz dostępu do API (F01)

Kto może wywołać którą operację. **Plik generowany** z kontraktu
`api/kontrakt_dostepu.py` poleceniem `python manage.py macierz_dostepu --zapisz`;
test pilnuje, że jest aktualny. Nie edytować ręcznie.

Każdy wiersz jest sprawdzany prawdziwymi żądaniami w
`api/tests/test_kontrakt_dostepu.py` - opis metody i wyniki są w
[kontrakt-dostepu.md](kontrakt-dostepu.md).

## Jak czytać

- **Anonim** - bez logowania i bez klucza.
- **Sam klucz widgetu** - jawny klucz z kodu strony klienta; widzi go każdy odwiedzający.
- **Podgląd**, **Pracownik**, **Właściciel** - role w zespole firmy, z tokenem
  zalogowanego konta i kluczem własnej firmy.
- „tak” przy operacji publicznej znaczy, że kontrola dostępu nie odrzuca - widok
  sprawdza resztę sam (klucz widgetu, podpis Stripe, token z e-maila, limit).
- „tak” przy koncie dotyczy wyłącznie własnego konta zalogowanej osoby.
- Nikt nie sięga danych innej firmy: właściciel firmy B dostaje 403 albo 404
  na każdej operacji z identyfikatorem obiektu firmy A, a token firmy A z kluczem
  firmy B - 403 wszędzie poza operacjami publicznymi i własnym kontem.

Operacji: 97.

## Logowanie, rejestracja i hasło

| Operacja | Opis | Anonim | Sam klucz widgetu | Podgląd | Pracownik | Właściciel |
|---|---|---|---|---|---|---|
| `POST /api/accounts/accept-invite/` | Przyjmij zaproszenie i załóż konto | tak | tak | tak | tak | tak |
| `POST /api/accounts/invitations/` | Zaproś osobę do zespołu | - | - | - | - | tak |
| `GET /api/accounts/invitations/list/` | Lista zaproszeń | - | - | - | - | tak |
| `POST /api/accounts/invitations/wyslij/{token_wysylki}/` | Wyślij zaproszenie na adres, na który je wystawiono | tak | tak | tak | tak | tak |
| `DELETE /api/accounts/invitations/{pk}/` | Cofnij zaproszenie | - | - | - | - | tak |
| `GET /api/accounts/invitations/{token}/preview/` | Sprawdź ważność zaproszenia | tak | tak | tak | tak | tak |
| `POST /api/accounts/login/` | Logowanie | tak | tak | tak | tak | tak |
| `POST /api/accounts/login/2fa/` | Drugi krok logowania | tak | tak | tak | tak | tak |
| `POST /api/accounts/logout/` | Wyloguj | tak | tak | tak | tak | tak |
| `POST /api/accounts/password-change/` | Zmiana własnego hasła | - | - | tak | tak | tak |
| `POST /api/accounts/password-reset/confirm/` | Ustawienie nowego hasła z linku | tak | tak | tak | tak | tak |
| `POST /api/accounts/password-reset/preview/` | Sprawdzenie linku do resetu hasła | tak | tak | tak | tak | tak |
| `POST /api/accounts/password-reset/request/` | Prośba o link do resetu hasła | tak | tak | tak | tak | tak |
| `POST /api/accounts/register/` | Rejestracja nowej firmy | tak | tak | tak | tak | tak |
| `POST /api/accounts/registration/activate/` | Aktywacja konta z linku w e-mailu | tak | tak | tak | tak | tak |
| `POST /api/accounts/registration/preview/` | Sprawdzenie linku aktywacyjnego | tak | tak | tak | tak | tak |
| `POST /api/accounts/registration/resend/` | Ponowne wysłanie linku aktywacyjnego | tak | tak | tak | tak | tak |
| `POST /api/accounts/token/refresh/` | Odswiez token dostepu | tak | tak | tak | tak | tak |

## Widget na stronie klienta

| Operacja | Opis | Anonim | Sam klucz widgetu | Podgląd | Pracownik | Właściciel |
|---|---|---|---|---|---|---|
| `POST /api/widget/chat/` | Zadaj pytanie botowi | tak | tak | tak | tak | tak |
| `POST /api/widget/chat/stream/` | Zadaj pytanie botowi (strumieniowo) | tak | tak | tak | tak | tak |
| `POST /api/widget/contact/` | Zostaw kontakt do siebie | tak | tak | tak | tak | tak |
| `GET /api/widget/faq/` | FAQ firmy | tak | tak | tak | tak | tak |
| `POST /api/widget/feedback/` | Oceń odpowiedź bota | tak | tak | tak | tak | tak |
| `GET /api/widget/rozmowa/{session_id}/` | Czy rozmowa została usunięta | tak | tak | tak | tak | tak |

## Konto, bezpieczeństwo i firma

| Operacja | Opis | Anonim | Sam klucz widgetu | Podgląd | Pracownik | Właściciel |
|---|---|---|---|---|---|---|
| `GET /api/accounts/2fa/` | Stan drugiego składnika | - | - | tak | tak | tak |
| `POST /api/accounts/2fa/potwierdz/` | Potwierdź konfigurację kodem | - | - | tak | tak | tak |
| `POST /api/accounts/2fa/rozpocznij/` | Rozpocznij konfigurację | - | - | tak | tak | tak |
| `POST /api/accounts/2fa/wylacz/` | Wyłącz drugi składnik | - | - | tak | tak | tak |
| `GET /api/accounts/dane-rozliczeniowe/` | Dane do faktury | - | - | - | - | tak |
| `PUT /api/accounts/dane-rozliczeniowe/` | Dane do faktury | - | - | - | - | tak |
| `PATCH /api/accounts/dane-rozliczeniowe/` | Dane do faktury | - | - | - | - | tak |
| `GET /api/accounts/dziennik/` | Dziennik audytowy firmy | - | - | - | - | tak |
| `GET /api/accounts/firma/` | Ustawienia firmy | - | - | - | - | tak |
| `PATCH /api/accounts/firma/` | Zmień ustawienia firmy | - | - | - | - | tak |
| `GET /api/accounts/me/` | Dane zalogowanego użytkownika | - | - | tak | tak | tak |
| `GET /api/accounts/sessions/` | Własne aktywne sesje logowania | - | - | tak | tak | tak |
| `POST /api/accounts/sessions/revoke-others/` | Wylogowanie pozostałych własnych sesji | - | - | tak | tak | tak |
| `POST /api/accounts/sessions/{session_uuid}/revoke/` | Wylogowanie jednej własnej sesji | - | - | tak | tak | tak |

## Wiedza bota

| Operacja | Opis | Anonim | Sam klucz widgetu | Podgląd | Pracownik | Właściciel |
|---|---|---|---|---|---|---|
| `POST /api/documents-upload/` | Wgraj dokument | - | - | - | tak | tak |
| `GET /api/documents/` | Lista dokumentów | - | - | tak | tak | tak |
| `GET /api/documents/uzycie/` | Ile miejsca zajmuje baza wiedzy | - | - | tak | tak | tak |
| `GET /api/documents/{document_id}/chunks/` | Fragmenty dokumentu w wyszukiwaniu | - | - | tak | tak | tak |
| `GET /api/documents/{pk}/` | Szczegóły dokumentu | - | - | tak | tak | tak |
| `GET /api/documents/{pk}/` | Szczegóły dokumentu (trasa przesłonięta przez router) | - | - | tak | tak | tak |
| `DELETE /api/documents/{pk}/` | Usuń dokument razem z plikiem | - | - | - | tak | tak |
| `GET /api/documents/{pk}/download/` | Pobranie pliku dokumentu | - | - | tak | tak | tak |
| `PATCH /api/documents/{pk}/wyszukiwanie/` | Włącz lub wyłącz dokument w wyszukiwaniu | - | - | - | tak | tak |
| `GET /api/faq/` | Lista wpisów FAQ | - | - | tak | tak | tak |
| `POST /api/faq/` | Dodanie wpisu FAQ | - | - | - | tak | tak |
| `GET /api/faq/{pk}/` | Wpis FAQ | - | - | tak | tak | tak |
| `PUT /api/faq/{pk}/` | Zmiana wpisu FAQ | - | - | - | tak | tak |
| `PATCH /api/faq/{pk}/` | Zmiana wpisu FAQ | - | - | - | tak | tak |
| `DELETE /api/faq/{pk}/` | Usunięcie wpisu FAQ | - | - | - | tak | tak |
| `GET /api/knowledge/` | Opis działalności i regulamin | - | - | tak | tak | tak |
| `PATCH /api/knowledge/` | Opis działalności i regulamin | - | - | - | tak | tak |
| `GET /api/website-sources/` | Lista stron WWW w wiedzy | - | - | tak | tak | tak |
| `POST /api/website-sources/` | Dodanie strony WWW | - | - | - | tak | tak |
| `GET /api/website-sources/{pk}/` | Strona WWW w wiedzy | - | - | tak | tak | tak |
| `PUT /api/website-sources/{pk}/` | Zmiana strony WWW | - | - | - | tak | tak |
| `PATCH /api/website-sources/{pk}/` | Zmiana strony WWW | - | - | - | tak | tak |
| `DELETE /api/website-sources/{pk}/` | Usunięcie strony WWW z wiedzy | - | - | - | tak | tak |
| `POST /api/website-sources/{pk}/recrawl/` | Odśwież treść ze strony teraz | - | - | - | tak | tak |

## Rozmowy, kontakty i prywatność

| Operacja | Opis | Anonim | Sam klucz widgetu | Podgląd | Pracownik | Właściciel |
|---|---|---|---|---|---|---|
| `POST /api/chat/` | Zadaj pytanie botowi z panelu | - | - | - | tak | tak |
| `GET /api/chat/export/` | Pobierz historię rozmów jako CSV | - | - | - | tak | tak |
| `POST /api/chat/feedback/` | Oceń odpowiedź bota w rozmowie testowej (panel) | - | - | tak | tak | tak |
| `POST /api/chat/import/` | Wgraj historię rozmów z pliku CSV | - | - | - | tak | tak |
| `GET /api/chat/logs/` | Historia pytań i odpowiedzi | - | - | tak | tak | tak |
| `GET /api/chat/test/` | Dotychczasowy przebieg rozmowy testowej | - | - | tak | tak | tak |
| `POST /api/chat/test/` | Zadaj pytanie własnemu botowi | - | - | tak | tak | tak |
| `DELETE /api/chat/test/` | Wyczyść rozmowę testową | - | - | tak | tak | tak |
| `GET /api/contact-requests/` | Lista zapytań od odwiedzających | - | - | tak | tak | tak |
| `PUT /api/contact-requests/{pk}/` | Oznaczenie zapytania jako obsłużone | - | - | - | tak | tak |
| `PATCH /api/contact-requests/{pk}/` | Oznaczenie zapytania jako obsłużone | - | - | - | tak | tak |
| `GET /api/privacy/` | Okres przechowywania danych i polityka prywatności | - | - | tak | tak | tak |
| `PATCH /api/privacy/` | Okres przechowywania danych i polityka prywatności | - | - | - | tak | tak |
| `DELETE /api/privacy/conversations/{session_id}/` | Usuń wszystkie dane jednej rozmowy | - | - | - | tak | tak |

## Wygląd i witryny widgetu

| Operacja | Opis | Anonim | Sam klucz widgetu | Podgląd | Pracownik | Właściciel |
|---|---|---|---|---|---|---|
| `GET /api/widget-domains/` | Witryny, na których działa widget | - | - | tak | tak | tak |
| `GET /api/widget-domains/{pk}/` | Witryny, na których działa widget | - | - | tak | tak | tak |
| `DELETE /api/widget-domains/{pk}/` | Witryny, na których działa widget | - | - | - | tak | tak |
| `GET /api/widget-settings/` | Wygląd widgetu | tak | tak | tak | tak | tak |
| `GET /api/widget-settings/mine/` | Branding widgetu (odczyt i zapis) | - | - | tak | tak | tak |
| `PATCH /api/widget-settings/mine/` | Branding widgetu (odczyt i zapis) | - | - | - | tak | tak |

## Zespół

| Operacja | Opis | Anonim | Sam klucz widgetu | Podgląd | Pracownik | Właściciel |
|---|---|---|---|---|---|---|
| `GET /api/users/` | Lista osób w zespole | - | - | - | tak | tak |
| `POST /api/users/` | Dodanie osoby do zespołu | - | - | - | - | tak |
| `GET /api/users/{pk}/` | Osoba w zespole | - | - | - | tak | tak |
| `PUT /api/users/{pk}/` | Zmiana roli osoby | - | - | - | - | tak |
| `PATCH /api/users/{pk}/` | Zmiana roli osoby | - | - | - | - | tak |
| `DELETE /api/users/{pk}/` | Usunięcie osoby z zespołu | - | - | - | - | tak |

## Pulpit i diagnostyka

| Operacja | Opis | Anonim | Sam klucz widgetu | Podgląd | Pracownik | Właściciel |
|---|---|---|---|---|---|---|
| `GET /api/analytics/` | Podsumowanie działania chatbota | - | - | tak | tak | tak |
| `GET /api/diagnostyka/adres/` | Jak serwer widzi adres odwiedzającego | - | - | tak | tak | tak |
| `GET /api/diagnostyka/zadania/` | Czy zadania w tle się wykonują | - | - | tak | tak | tak |

## Płatności

| Operacja | Opis | Anonim | Sam klucz widgetu | Podgląd | Pracownik | Właściciel |
|---|---|---|---|---|---|---|
| `GET /api/billing/cennik/` | Cennik dla strony sprzedażowej | tak | tak | tak | tak | tak |
| `GET /api/billing/checkout-session/{session_id}/` | Stan konkretnego zakupu | - | - | - | - | tak |
| `POST /api/billing/create-checkout-session/` | Rozpocznij płatność za plan | - | - | - | - | tak |
| `GET /api/billing/plans/` | Cennik i bieżąca subskrypcja | - | - | tak | tak | tak |
| `POST /api/billing/portal/` | Otwórz portal klienta Stripe | - | - | - | - | tak |
| `POST /api/billing/webhook/` | Powiadomienie od Stripe (podpisane) | tak | tak | tak | tak | tak |
