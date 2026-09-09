# Roadmapa napraw po audycie SaaS

Data rozpoczęcia: 9.09.2026. Użytkownik zatwierdził rozpoczęcie napraw po audycie.
Ta lista obejmuje wszystkie 25 grup ustaleń. Status dotyczy kodu lokalnego;
gotowość produkcyjna wymaga osobnego sprawdzenia wdrożenia.

Zasada realizacji: odtworzenie błędu → poprawka → test regresyjny → kontrola
powiązanych przepływów → zapis wyniku. Zmiany dostępu, pieniędzy i retencji
sprawdzamy także przy równoległych operacjach i po awarii.

## Kolejność i warunki odbioru

| Etap | Ustalenia | Zakres i warunek odbioru | Status |
|---|---|---|---|
| 1. Izolacja i role | F01, F02, F03 | JWT/klucz/role/metody nie umożliwiają przekroczenia granicy firmy; brak samodzielnego awansu i utraty ostatniego właściciela; CSV działa na własnej firmie bez klucza widgetu | Zakończony lokalnie; bez wdrożenia |
| 2. Prywatność i ochrona danych | F04, F05, F12, F13 | Prywatny storage dokumentów/kopii, podpisane odczyty i szyfrowanie; retencja zachowuje świeże wiadomości; bezpieczny Docker i aktualne zależności | Do wykonania |
| 3. Bezpieczne wejścia i koszty | F06, F08, F09, F23 | Kontrola SSRF/DNS/redirectów i uploadu, budżety oraz rezerwacje wiadomości; formularze odporne na awarie i spam | Do wykonania |
| 4. Konta i sesje | F07, F14, F15; reset hasła z F22 | Walidacja haseł, adresów i zaproszeń; atomowe miejsca/kody; MFA admina; prawidłowe cookies/CSRF; bezpieczne odzyskiwanie konta | Do wykonania |
| 5. Wiedza i cykl życia danych | F10, F17, F18, F19, F25 | Kompletny import, atomowa publikacja embeddingów i usuwanie pochodnych, poprawne CSV i feedback, wyszukiwanie FAQ i regresja RAG | Do wykonania |
| 6. Płatności | F11; status płatności z F22 | Idempotencja Checkout/webhooków, identyfikatory i okresy Stripe, retry/uzgadnianie; UI potwierdza konkretny zakup | Do wykonania |
| 7. Wydajność i obsługa | F16, F20, F21, F24; pozostałe F22 | Paginacja/N+1, SLO, dziennik i minimalizacja danych, alarmy/kopie/restore, obowiązkowe bramki CI, pełne stany UI | Do wykonania |
| 8. Odbiór komercyjny | Wszystkie | Staging zgodny z produkcją, negatywne testy dostępu, przegląd infrastruktury, obciążenie, odtworzenie kopii, płatności testowe, onboarding i dostępność | Do wykonania |

Najpierw zamykamy dostęp do cudzych danych. Weryfikacja rzeczywistego storage
z etapu 2 jest kolejnym priorytetem — lokalny kod nie dowodzi prywatności
już zapisanych dokumentów i kopii. W tym samym etapie naprawiamy retencję,
ponieważ błąd grozi utratą świeżych danych. SSRF i koszty zamykamy przed
większą przebudową sesji i odzyskiwania konta. Etapy nie są zgodą na publikowanie zmian
ani wykonywanie rzeczywistych płatności czy zmian w kontach usługowych.

## Etap 1 — zakres bieżącej poprawki

- [x] F01: throttling nie wybiera ani nie podmienia firmy na podstawie nagłówka.
- [x] F01: sprzeczne poświadczenia i nieprawidłowy JWT nie przechodzą inną ścieżką.
- [x] F01: zapytania i uprawnienia sprawdzają zgodność firmy z użytkownikiem.
- [x] F02: listę zespołu czyta właściciel/pracownik; tworzenie, zmiany i usuwanie
  kont wykonuje wyłącznie właściciel w swojej firmie.
- [x] F02: nie można usunąć, dezaktywować ani zdegradować ostatniego aktywnego
  właściciela, również w dwóch równoległych żądaniach.
- [x] F02: bezpośrednie tworzenie kont respektuje limit miejsc.
- [x] F03: import/eksport CSV korzysta z firmy zalogowanego użytkownika.
- [x] Nowe testy odtwarzają błędy przed poprawką i przechodzą po niej.
- [x] Dotychczasowy pakiet backendu przechodzi; kontrola lint i diff zakończona.

Ograniczenia etapu: pełna atomowość przyjmowania zaproszeń należy do etapu 4;
sanityzacja, strumieniowanie i transakcyjność treści CSV do etapu 5;
budżety czatu i rezerwacja wiadomości do etapu 3. Zamknięcie F01–F03 nie
oznacza zamknięcia tych osobnych problemów.

### Kontrakt dostępu po etapie 1

| Żądanie | Zachowanie |
|---|---|
| Panel z JWT A, bez klucza widgetu | Dostęp według roli, wyłącznie do firmy A |
| Panel z JWT A i kluczem A | Zachowana zgodność ze starszym klientem |
| JWT A i klucz B lub błędny klucz | 403; brak odczytu/zapisu i brak podmiany firmy |
| Błędny/wygasły JWT z poprawnym kluczem | 401; brak przejścia na uwierzytelnienie samym kluczem |
| Publiczny klucz bez JWT | Publiczny widget działa; chronione zasoby panelu zwracają 401 |
| Własna tożsamość i ID obiektu B | 404 w zasobach ograniczonych querysetem do firmy A |
| Odczyt listy zespołu | Właściciel/pracownik; viewer otrzymuje 403 |
| Zmiana konta/roli lub usunięcie | Wyłącznie właściciel; ponowna kontrola uprawnień po uzyskaniu blokady firmy |
| Ostatni aktywny właściciel | Nie można usunąć, wyłączyć ani zdegradować; 400 |
| Import/eksport CSV | JWT i uprawnienia właściciela/pracownika; klucz widgetu nie jest wymagany |

Ochrona ostatniego właściciela używa transakcji i blokady rekordu firmy w
PostgreSQL. Testy SQLite nie są wystarczającym dowodem tej własności.
Dozwolone usunięcie własnego konta przy obecności drugiego właściciela
zachowuje nazwę autora w dzienniku bez FK do nieistniejącego już użytkownika.
Pełny zakres usprawnień dziennika z F20 nadal pozostaje otwarty.

## Historia weryfikacji

- Punkt odniesienia audytu: 1128 testów backendu, 72 jednostkowe frontendu,
  62 przeglądarkowe; mimo tego odtworzone luki dostępu.
- Pierwszy zestaw nowych prób przed poprawką: 56 niepowodzeń, 50 sukcesów;
  dodatkowo błąd integralności dziennika przy usunięciu ostatniego właściciela.
- Po poprawce: 185 testów dostępu, ról, CSV, logowania, limitów, zaproszeń i
  schematu API przeszło; po rozszerzeniu przypadków 131 testów granic/dziennika
  przeszło. Cztery przypadki współbieżnych zmian właścicieli przeszły na PostgreSQL.
- Pierwsza pełna regresja: 1250 testów przeszło; jeden dawny test oczekiwał
  nieobsłużonego wyjątku dla błędnego UUID klucza. Zaktualizowano go do
  właściwego kontraktu: HTTP 401 z komunikatem, zamiast wyjątku/500.
- Końcowa pełna regresja z pomiarem pokrycia: **1251 passed**, 8 ostrzeżeń
  Django o przyszłej zmianie domyślnego schematu URL, 521,22 s. W tym **123
  nowe przypadki** w `api/tests/test_access_boundaries.py`.
- Pokrycie według konfiguracji repozytorium/CI: **87,86%** z uwzględnieniem
  gałęzi; wymagany próg **83%** osiągnięty.
- Ruff zmienionych plików: bez błędów; w całym backendzie 47 istniejących
  zgłoszeń przy progu CI 50. Formatowanie: 252 pliki zgodne. Bandit zmienionego
  kodu produkcyjnego: brak zgłoszeń. `git diff --check`: bez problemów.
- Testy wykonujemy poza repozytorium, bez plików env, na syntetycznych danych
  i osobnej bazie PostgreSQL; połączenia z zewnętrznymi usługami są blokowane.
- Środowisko lokalnej weryfikacji: Python 3.12.14, PostgreSQL 15.1 + pgvector.
  CI nadal musi sprawdzić deklarowany Python 3.11/PostgreSQL 16. Nie zmieniono
  schematu danych, zależności ani kodu frontendu/witryny; nie wykonywano wdrożenia.
- Gałąź: `codex/audit-access-control`. Następny etap: prywatność dokumentów
  i backupów, poprawność retencji, kontekst Docker i podatne zależności.
