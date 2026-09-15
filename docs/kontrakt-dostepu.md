# Kontrakt dostępu do API (etap 8)

Stan na 15.09.2026, wersja 2.6.1. Pierwsza część odbioru komercyjnego z
[roadmapy](roadmapa-po-audycie.md): pełny negatywny test dostępu.

## Po co

Dotychczasowe testy granic (`api/tests/test_access_boundaries.py`) sprawdzały
wybrane końcówki. Luka w końcówce spoza tej listy przechodziła przez zielony
zestaw testów. Teraz każda trasa `/api/` i każda jej metoda ma zapisaną politykę
w `api/tests/test_kontrakt_dostepu.py`, a nowa końcówka bez wpisu zatrzymuje CI.

## Polityki

| Polityka | Kto przechodzi | Przykłady |
|---|---|---|
| publiczna | każdy; własne kontrole w widoku (klucz widgetu, podpis, token z e-maila) | logowanie, rejestracja, reset hasła, widget, cennik, webhook Stripe |
| konto | każdy zalogowany, wyłącznie własne konto | `me`, drugi składnik, sesje, zmiana hasła, przegląd planu |
| członek | każda rola firmy, także `viewer` | listy i podglądy wiedzy, historia rozmów, pulpit, czat testowy |
| pracownik | właściciel i pracownik | zmiany wiedzy i ustawień, eksport i import CSV, czat panelu, usunięcie rozmowy na żądanie, lista zespołu |
| właściciel | tylko właściciel | zmiany zespołu i zaproszenia, dane firmy i do faktury, dziennik, płatności |

Pełna lista tras jest w słowniku `KONTRAKT` w teście.

## Co sprawdza test

Uprawnienia nie są czytane z klas widoków: akcje viewsetów nadpisują
`permission_classes`, a część widoków zmienia je w metodzie. Rozstrzyga
odpowiedź serwera na prawdziwe żądanie.

1. **Kompletność.** Zbiór tras i metod z resolvera Django musi być równy
   kluczom `KONTRAKT` - brak wpisu i wpis martwy to błąd.
2. **Anonim** (bez tokenu i klucza) nie przechodzi żadnej trasy poza publicznymi: 401 albo 403.
3. **Sam klucz widgetu** nie otwiera niczego poza publicznymi - klucz jest
   jawny w kodzie strony klienta.
4. **Viewer z własnym kluczem** dostaje 403 na każdej trasie pracownika i właściciela.
5. **Pracownik z własnym kluczem** dostaje 403 na każdej trasie właściciela.
6. **Token firmy A z kluczem firmy B** dostaje 403 wszędzie poza publicznymi i kontem.
7. **Właściciel firmy B** nie sięga obiektów firmy A: 403 albo 404 na każdej trasie z identyfikatorem.
8. **Kontrola pozytywna:** właściciel firmy A przechodzi kontrolę każdego
   odczytu. Bez niej testy odmowy byłyby zielone także wtedy, gdyby środowisko
   testu odrzucało wszystko z innego powodu. Dwa odczyty wołające usługę
   zewnętrzną (stan zakupu w Stripe, ping brokera zadań) są w niej pominięte;
   ich odmowy sprawdzają punkty 2-7, bo kontrola uprawnień zapada przed kodem widoku.

## Znalezione i naprawione

| Luka | Odtworzenie | Poprawka |
|---|---|---|
| `POST /api/chat/` (czat panelu) dostępny dla roli `viewer`. Każda odpowiedź rezerwuje wiadomość z płatnego limitu planu i liczy się jak rozmowa odwiedzającego | viewer z własnym kluczem przechodził do walidacji (400 zamiast 403) | tylko właściciel i pracownik; panel z tej końcówki nie korzysta, `viewer` sprawdza bota bez kosztów w czacie testowym |
| `GET /api/` (korzeń routera DRF) odpowiadał 200 z listą końcówek panelu na sam jawny klucz widgetu | 200 zamiast 401/403 | `SimpleRouter` zamiast `DefaultRouter`; korzeń nie był używany ani przez panel, ani przez backend |
| `GET /api/documents/<id>/chunks/` dla dokumentu innej firmy zwracał 200 z pustą listą | 200 zamiast 403/404 | 404, jak pozostałe zasoby z identyfikatorem; treści nie zdradzał, ale mówił nieprawdę o istnieniu dokumentu |

Trzy testy czatu i trzy logów promptów tworzyły konto z domyślną rolą
`viewer`; dostały rolę pracownika, bo sprawdzają czat, a nie role.

## Co zostaje z etapu 8

| Punkt | Stan | Zależy od |
|---|---|---|
| Negatywny test dostępu | ten dokument | - |
| Staging zgodny z produkcją | nie istnieje | decyzji właściciela (nowa instancja poza obecnym budżetem) |
| Test obciążeniowy | brak narzędzia | decyzji o narzędziu i środowisku; bez stagingu tylko pomiar lokalny |
| Odtworzenie kopii | czeka | odbioru F21 przez właściciela |
| Płatności testowe | odebrane w F11 (tryb testowy Stripe) | - |
| Onboarding i dostępność | lista pierwszych kroków i stany panelu gotowe | odbioru na nowym koncie; automatyczny przegląd dostępności wymaga nowej zależności w panelu |
| Przegląd infrastruktury | odbiór z 11.09.2026 w roadmapie | ponowienia po wdrożeniu 2.6.1 |

## Weryfikacja

- Kontrakt na kodzie sprzed poprawek: 4 czerwone przypadki (martwy wpis, korzeń API,
  fragmenty obcego dokumentu, czat dla roli viewer).
- Po poprawkach: kontrakt, czat, logi promptów, schemat OpenAPI, dotychczasowe granice
  dostępu i dokumenty - 719 passed. Kontrakt działa w około 10 sekund.
- Mutacje wobec kontraktu: 6 z 7 złapanych. Żywa: usunięcie `verified_request_tenant`
  z `IsTenantMember` - na poziomie HTTP tę samą kontrolę robi wcześniej `TenantMiddleware`,
  więc kontrakt nie odróżni drugiej warstwy; pilnuje jej test granic bez middleware.
