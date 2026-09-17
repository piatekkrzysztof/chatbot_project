# Dziennik, logi i przepływy danych (F20)

Stan na 15.09.2026, wersja 2.5.0. Etap 7 [roadmapy](roadmapa-po-audycie.md).

Dokument odpowiada na trzy pytania, które zada audytor klienta albo urząd po
incydencie: co zapisujemy o działaniach na koncie, gdzie trafiają dane osobowe
poza naszą bazę i jak długo je trzymamy. Część 1 F20 zamyka luki w zapisie
i w logach. **Nie włącza żadnego nowego automatycznego usuwania danych.**

Aktualizacja 17.09.2026: odbiór F21 jest zamknięty
([protokół](odbior-f21.md#wynik-odbioru---17092026)), więc warunek, który
wstrzymywał retencję, przestał obowiązywać. Powstał raport `raport_retencji`
(ostatnia sekcja) - **nadal nic nie usuwa**, ale pokazuje liczby, na których
właściciel może oprzeć decyzję o okresach.

## Część 1: luki i poprawki

Każda luka została najpierw odtworzona testem na kodzie sprzed zmiany
(14 czerwonych testów), a poprawka sprawdzona mutacjami.

| Luka | Skutek | Poprawka |
|---|---|---|
| Eksport rozmów (`GET /api/chat/export/`) i pobranie dokumentu (`GET /api/documents/<id>/download/`) nie zostawiały wpisu, bo dziennik zapisywał tylko żądania zmieniające dane | Brak odpowiedzi na pytanie "kto wyniósł nasze rozmowy", choć ekran dziennika wymienia eksporty | Middleware zapisuje także odczyty z listy `ODCZYTY_W_DZIENNIKU` (po nazwie trasy); test pilnuje, że nazwy tras istnieją |
| Logowanie, drugi krok, wylogowanie, potwierdzenie rejestracji, przyjęcie zaproszenia i nowe hasło z linku zapisywały się bez osoby i bez firmy | Właściciel nie widział w dzienniku ani jednego logowania, także po przejęciu konta pracownika | Widok wskazuje autora po udanym sprawdzeniu hasła, kodu albo tokenu (`accounts/dziennik.py`); firma pochodzi z konta tej osoby |
| Sentry dostawał pełny adres żądania i jego zapytanie | Token zaproszenia (otwiera założenie konta w firmie), identyfikator rozmowy odwiedzającego i wyszukiwania z panelu, także e-maile, w zewnętrznej usłudze | `redact_credentials` usuwa `query_string`, a w adresie i nazwie transakcji zamienia UUID na `[uuid]` i sesję Stripe na `[sesja-stripe]` |
| Nieudana wysyłka zaproszenia logowała adres e-mail zapraszanego | Adres osoby bez konta w logach Rendera i w okruszkach Sentry | Log podaje numer zaproszenia |

Nieudane próby (złe hasło, zły kod drugiego składnika) **zostają anonimowe**.
Przypisanie ich do konta pozwalałoby każdemu dopisywać wpisy do dziennika
cudzej firmy, znając sam login. Wpis ma wtedy adres IP i wynik, ale nie osobę.

## Co zapisuje dziennik audytowy

Model `WpisDziennika`: firma, osoba (i kopia jej nazwy, która przeżywa
usunięcie konta), czas, metoda, ścieżka, status odpowiedzi, adres IP. Treści
żądań nie są zapisywane nigdy.

Zapisywane:

- każde żądanie `POST`, `PUT`, `PATCH`, `DELETE` do `/api/`,
- odczyty wynoszące dane: eksport rozmów do CSV i pobranie pliku dokumentu,
  także odmowy (np. 403 dla roli `viewer`),
- zdarzenia dostępu z osobą i firmą: logowanie po poprawnym haśle, drugi krok,
  wylogowanie, potwierdzenie rejestracji, przyjęcie zaproszenia, nowe hasło
  z linku.

Niezapisywane, świadomie:

- ruch widgetu (`/api/widget/`) - to odwiedzający strony klienta, nie działania
  w panelu; zamieniłby dziennik w log dostępu,
- webhook Stripe - ma własny ślad po stronie Stripe,
- zwykłe odczyty panelu (listy, podglądy),
- odświeżenie tokenu dostępu zapisuje się bez osoby: panel robi to sam przy
  każdym wygaśnięciu tokenu i przypisane wpisy zasypałyby dziennik firmy.

Ścieżka zawiera identyfikatory obiektów, w tym identyfikator rozmowy usuniętej
na żądanie (`DELETE /api/privacy/conversations/<id>/`). To celowe: wpis jest
dowodem, że żądanie usunięcia wykonano.

Dziennik czyta tylko właściciel firmy, wyłącznie wpisy własnej firmy
(`GET /api/accounts/dziennik/`), bez możliwości edycji ani usuwania.

## Logi aplikacji

- Projekt nie ma własnej konfiguracji `LOGGING`. W usłudze web komunikaty od
  poziomu WARNING trafiają na standardowe wyjście błędów, a stamtąd do logów
  Rendera. Worker Celery loguje od poziomu INFO.
- Integracja Sentry zbiera komunikaty od INFO jako okruszki przy zdarzeniu,
  więc log aplikacji w praktyce trafia też do Sentry. Stąd zasada: w logu numer
  obiektu, nie adres e-mail ani treść.
- Przegląd wszystkich wywołań `logger.*` poza testami (skan składni, także
  wywołań wielowierszowych): jedynym adresem e-mail w logu było zaproszenie,
  poprawione w tej części. Pozostałe argumenty to numery obiektów i nazwy firm
  (dane firmy-klienta, nie osób odwiedzających).
- Wolne żądania (`PomiarCzasuMiddleware`) logują wzorzec trasy, nie adres, więc
  tokeny z adresu tam nie trafiają - patrz [SLO](slo-i-czasy-odpowiedzi.md).
- Gunicorn działa bez `--access-logfile`, więc aplikacja nie prowadzi logu
  dostępu. Render może prowadzić własny log żądań HTTP; jego zakres i czas
  przechowywania wynikają z planu Rendera - **do sprawdzenia przez właściciela
  w panelu Rendera**.

## Sentry

- `send_default_pii=False`, bez treści żądań, ciasteczek, zmiennych lokalnych
  i argumentów zadań Celery.
- SDK sam usuwa nagłówki `Authorization`, `Cookie`, `X-API-Key`,
  `X-Forwarded-For`, `X-Real-IP` i adres `REMOTE_ADDR`.
- Od 2.5.0 bez zapytania z adresu; UUID i sesje Stripe zamaskowane w adresie
  i nazwie transakcji.
- Próbkowanie czasu żądań 10%. Czas przechowywania zdarzeń wynika z ustawień
  organizacji w Sentry - **do sprawdzenia przez właściciela**.

## Kto przetwarza dane poza naszą bazą

| Usługa | Co dostaje | Po co |
|---|---|---|
| Render | Całość: API, worker, PostgreSQL, Redis, logi | Hosting |
| Cloudflare R2 | Pliki dokumentów w prywatnym magazynie, pełne kopie zapasowe | Przechowywanie plików |
| OpenAI | Pytania odwiedzających, fragmenty bazy wiedzy, treść dokumentów do wektorów | Odpowiedzi bota i wyszukiwanie |
| Stripe | Dane do faktury (nazwa, adres, NIP), e-mail konta; dane karty nie przechodzą przez nas | Płatności |
| Resend (SMTP) | Adresy i treść wiadomości: aktywacja, zaproszenia, reset i zmiana hasła, raporty, powiadomienie o zapytaniu z czatu razem z danymi kontaktowymi odwiedzającego | Poczta |
| Sentry | Błędy i próbki czasu żądań, w zakresie opisanym wyżej | Diagnostyka |

Hosting panelu (Next.js) jest poza tym repozytorium.

## Dane osobowe i czas przechowywania

"Automatycznie" oznacza zadanie w harmonogramie istniejącego workera.

| Dane | Gdzie | Usuwanie dziś | Otwarte |
|---|---|---|---|
| Rozmowy odwiedzających i oceny odpowiedzi (identyfikator rozmówcy to zanonimizowany adres IP) | PostgreSQL | Automatycznie, codziennie 3:30, po okresie `data_retention_days` firmy (domyślnie 90 dni, 0 = bez usuwania); pojedyncza rozmowa na żądanie | - |
| Logi promptów i zużycia | PostgreSQL | Jak rozmowy | - |
| Zapytania kontaktowe (imię, e-mail lub telefon, wiadomość) | PostgreSQL; kopia w skrzynce właściciela firmy | Jak rozmowy; kopia w poczcie poza naszą kontrolą | - |
| Dokumenty i ich fragmenty (mogą zawierać dane osobowe wgrane przez klienta) | PostgreSQL, R2 | Gdy klient usunie dokument; od 2.8.1 plik znika z magazynu każdą drogą usunięcia, nie tylko przyciskiem w panelu ([opis](usuwanie-plikow.md)) | Pliki osierocone przed 2.8.1 - raport przed odbiorem F21 |
| Logo i awatar widgetu (obrazy wgrane przez klienta) | PostgreSQL, R2 | Z usunięciem firmy; poprzedni obraz przy wymianie (od 2.8.1) | - |
| Konta: login, e-mail, skrót hasła, drugi składnik, kody zapasowe | PostgreSQL | Z usunięciem konta | - |
| E-mail właściciela, dane do faktury | PostgreSQL, Stripe | Z usunięciem firmy; kopia w Stripe | - |
| Dziennik audytowy (osoba, adres IP, ścieżka) | PostgreSQL | Automatycznie, codziennie 3:45, po **12 miesiącach** | - |
| Sesje logowania (bez adresu IP) | PostgreSQL | Automatycznie, codziennie 3:45, **24 h po wygaśnięciu** | - |
| Rozpoczęte rejestracje (e-mail, dane firmy, bez hasła; dane czyszczone przy aktywacji) | PostgreSQL | Automatycznie, codziennie 3:45, po **7 dniach** | - |
| Zaproszenia (e-mail zapraszanego) | PostgreSQL | Automatycznie, codziennie 3:45: **30 dni od utworzenia**, i tylko te wygasłe albo wykorzystane do końca | - |
| Wyzwania drugiego składnika | PostgreSQL | Automatycznie, codziennie 3:45, **24 h po wygaśnięciu** | - |
| Kolejka powiadomień o zmianie hasła (adres odbiorcy) | PostgreSQL | Automatycznie, codziennie 3:45: **90 dni**, i tylko wysłane albo nieudane | - |
| Liczniki limitów (adres IP w kluczu) | Redis | Wygasają same razem z oknem limitu | - |
| Pełne kopie zapasowe (wszystko powyżej) | R2 | Polecenia kopii niczego nie usuwają | Retencja kopii - [harmonogram kopii](harmonogram-i-kontrola-kopii.md) |
| Logi Rendera, zdarzenia Sentry | Render, Sentry | Według ustawień usług | Do sprawdzenia przez właściciela |

Usunięcie danych w bazie nie usuwa ich z kopii zapasowych, dopóki kopia nie
wypadnie z rotacji. Dopóki retencja kopii nie jest ustalona, każdy okres
przechowywania z tabeli dotyczy bazy, a nie kopii.

## Jak to działa: `accounts/retencja.py`

Okresy i warunki „co jest do usunięcia" siedzą w **jednym module**, z którego
czyta i raport, i nocne zadanie. Dwie kopie tej samej reguły rozjeżdżają się po
cichu - a wtedy raport obiecuje jedno, a sprzątanie robi drugie i nikt tego nie
zauważy, bo obie liczby wyglądają wiarygodnie. To nie jest obawa teoretyczna:
pierwszy raport z produkcji pokazał zaproszenie sprzed jednego dnia jako
„bezużyteczne od ponad 90 dni", bo warunek wieku był napisany osobno dla każdej
gałęzi.

Podgląd przed operacją, której nie da się cofnąć:

```bash
python manage.py raport_retencji
```

Wypisuje dla każdego rodzaju danych: okres, ile jest wierszy, jak stary jest
najstarszy, **ile zniknie przy najbliższym przebiegu** i ile zostanie. Niczego
nie usuwa. To samo bez usuwania robi `purge_retencja --dry-run`; obie liczby
muszą się zgadzać, bo pochodzą z tej samej reguły.

Sprzątanie: `accounts.tasks_retencja.sprzataj_retencje`, codziennie **3:45 UTC**
na istniejącym workerze - kwadrans po sprzątaniu rozmów, żeby dwa zadania nie
zaczynały się w tej samej minucie na jednej bazie. Bez nowej usługi i bez kosztu.

Usuwanie idzie partiami po 1000 wierszy. Jedno `DELETE` na sto tysięcy wierszy
blokuje tabelę na czas, którego nikt nie przewidział; przy partiach przebieg
przerwany awarią zostawia bazę w stanie pośrednim, ale spójnym, a następny
przebieg kończy robotę. Osobny test to odtwarza.

Zadanie loguje wynik także wtedy, gdy nic nie znalazło. Cisza w logu nie
odróżnia przebiegu, który nic nie usunął, od przebiegu, którego nie było - ta
sama pomyłka zdarzyła się już przy monitorze kopii.

## Czego automat nie usunie nigdy

- **ważnego, niewykorzystanego zaproszenia** - to odebrałoby komuś dostęp do firmy;
- **ważnej sesji** - to wylogowałoby ludzi w trakcie pracy;
- **powiadomienia czekającego na wysyłkę** - to jedyny sygnał, jaki dostaje
  właściciel przy przejęciu konta;
- **rozmów odwiedzających** - mają własny okres, ustawiany przez klienta
  w panelu, i własne zadanie od dawna w harmonogramie.

Zmiana któregokolwiek okresu jest decyzją o danych klientów, a nie porządkami
w kodzie: osobny test przypina zatwierdzone wartości i zatrzymuje zmianę
zrobioną mimochodem.

## Weryfikacja

- Nowe testy na kodzie sprzed zmiany: 14 czerwonych (3 odczyty, 7 zdarzeń
  dostępu, 3 Sentry, 1 log zaproszenia); po zmianie zielone.
- Mutacje: 16 z 16 złapanych, m.in. zapis każdego GET, wskazanie autora przed
  sprawdzeniem hasła, brak firmy z konta, brak maskowania UUID, sesji Stripe
  i nazwy transakcji, adres e-mail z powrotem w logu.
- Pełny zestaw backendu: 2064 passed; 5 czerwonych to znane testy odtworzenia
  kopii bez bazy `saas_restore_*`, niezwiązane ze zmianą.
- Lista tras i metod do opisów w panelu wzięta z resolvera Django (wszystkie
  trasy `/api/`), nie z pamięci.
- Panel: `vitest` 145 passed, Playwright dziennik i responsywność 24 passed.
