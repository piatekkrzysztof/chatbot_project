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
| 1. Izolacja i role | F01, F02, F03 | JWT/klucz/role/metody nie umożliwiają przekroczenia granicy firmy; brak samodzielnego awansu i utraty ostatniego właściciela; CSV działa na własnej firmie bez klucza widgetu | PR #38 scalony; Render potwierdził wdrożenie na web i workerze |
| 2. Prywatność i ochrona danych | F04, F05, F12, F13 | Prywatny storage dokumentów/kopii, podpisane odczyty i szyfrowanie; retencja zachowuje świeże wiadomości; bezpieczny Docker i aktualne zależności | PR #39 i #40 scalone i wdrożone; prywatne magazyny oraz dostęp sprawdzone, odczyt legacy wyłączony; operacyjny zakres kopii, pełny restore i zależności pozostałych repozytoriów pozostają otwarte |
| 3. Bezpieczne wejścia i koszty | F06, F08, F09, F23 | Kontrola SSRF/DNS/redirectów i uploadu, budżety oraz rezerwacje wiadomości; formularze odporne na awarie i spam | F06: PR #42; F09: gałąź `codex/audit-safe-file-uploads`, walidacja i ograniczone procesy parserów. Odbiór wdrożenia otwarty. Następne: F08 koszty i rezerwacje, F23 formularz marketingowy |
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

## Etap 2a — retencja, obraz i zależności backendu

Gałąź `codex/audit-data-protection` powstała ze scalonego PR #38
(`8015bcb136f6e47c0149558e511a8ba7564f043d`). Przebieg CI tego commita na main
zakończył się powodzeniem. Stan wdrożenia usług nie został sprawdzony.

- F13: zwykły zapis wiadomości blokuje rozmowę i atomowo odświeża jej aktywność.
  Retencja pomija zablokowane rozmowy oraz ponownie sprawdza ich datę i faktyczne
  wiadomości pod blokadą. Chroni to także wiadomości zapisane przed naprawą,
  mimo nieaktualnego `last_message_at`.
- Polityka rozmów: usuwamy całą rozmowę po okresie nieaktywności. Świeża
  wiadomość zachowuje również starszy kontekst tej rozmowy. PromptLog,
  ChatUsageLog i ContactRequest wygasają niezależnie według `created_at`.
- F05: `.dockerignore` dopuszcza wybrane pliki runtime. Produkcyjny Dockerfile
  kopiuje wskazane pakiety i instaluje tylko `requirements.txt`; Compose wybiera
  osobny etap development z narzędziami testowymi.
- CI buduje obraz z syntetycznymi plikami przypominającymi sekrety i dane,
  następnie sprawdza ich nieobecność, kompletność kodu runtime i użytkownika
  bez uprawnień root. Lokalny silnik Docker jest niedostępny.
- F12, backend: DRF 3.16.0 → 3.17.2, poprawka CVE-2026-73228 i CVE-2026-73229.
  Skan `pip-audit -r requirements.txt` z 9.09.2026 nie zgłosił znanych podatności.
  Nie jest to wynik skanowania frontendu ani strony marketingowej.
- Nowe regresje odtwarzają utratę świeżych wiadomości, aktualizację aktywności,
  granicę okresu retencji, rollback zapisu, retencję logów/kontaktów, współbieżny
  zapis oraz limit wielkości JSON i formularzy na uwierzytelnionym API.

Pierwsza próba nowych testów retencji przed naprawą: 5 niepowodzeń i 2 sukcesy.
Po naprawie 46 testów retencji/czatu/prywatności przeszło. Rozszerzone przypadki
zostały dołączone do pełnej regresji. Wynik CI dla bieżącego commita jest
warunkiem scalenia; lokalna weryfikacja używa Pythona 3.12 i PostgreSQL 15.

Pierwsza pełna regresja: 1266 testów przeszło, 2 testy porównania fizycznego
rozmiaru tabeli nie przeszły; pokrycie 87,91%. Ten sam problem wystąpił już
8.09.2026 w [CI wcześniejszego main](https://github.com/piatekkrzysztof/chatbot_project/actions/runs/34251506770).
Testy obliczania przyrostu i ostrzeżeń używają teraz znanych odczytów rozmiaru,
zamiast wymagać od każdej bazy takiego samego przyrostu przy autovacuum i ponownym
wykorzystywaniu wolnych stron. Test rzeczywistego odczytu PostgreSQL pozostaje.
Kod narzędzia pomiarowego oraz jego próg ostrzegania nie zostały zmienione.

Końcowa pełna regresja: **1268 testów przeszło**, 8 ostrzeżeń Django o przyszłej
zmianie domyślnego schematu URL, 421,33 s; **87,92% pokrycia** przy progu 83%.
Etap dodaje 17 przypadków (13 retencji i 4 rozmiaru żądań). Ruff: 47 istniejących
zgłoszeń, 254 pliki zgodne z formatowaniem. Bandit zmienionego kodu produkcyjnego:
0 zgłoszeń. Wszystkie 7 zmienionych plików Python ma tę samą strukturę AST
co kod użyty do testów. Budowę i zawartość obrazu musi jeszcze sprawdzić CI.

Wersja aplikacji wzrasta do 1.0.6. Nie dodano migracji ani zmiennych środowiskowych.
Wdrożenie wymaga aktualizacji backendu i workera z tym samym commitem; nie wymaga
ponownego importu wiedzy ani ręcznego uruchamiania retencji na produkcji.

## Etap 2b — następny krok

- Potwierdzić dostawcę i rzeczywiste ustawienia publicznych oraz prywatnych
  magazynów. Kod nie dowodzi, że obecnie zapisane dokumenty są prywatne.
- Oddzielić zapis dokumentów i zaszyfrowanych kopii od publicznych logo;
  przygotować kontrolowaną migrację istniejących plików, weryfikację dostępu
  i odtworzenia oraz instrukcję konfiguracji usług przed przełączeniem zapisu.
- Usunąć podatności zależności frontendu i strony marketingowej w ich osobnych
  repozytoriach, z odpowiednimi testami i PR-ami.

F04 i całościowe F12 pozostają otwarte. Bieżąca poprawka nie zmienia istniejących
plików w magazynie, sekretów produkcyjnych ani konfiguracji usług hostingowych.

### Aktualizacja 2b — prywatne pliki

Gałąź `codex/audit-private-storage`, wydanie 2.0.0. Wymaga konfiguracji przed
automatycznym wdrożeniem: nowy zapis dokumentów jest zamknięty bez prywatnego
magazynu, a kopie wymagają niezależnego klucza Fernet. Odczyt starych dokumentów
pozostaje dostępny podczas migracji; nie ma publicznego URL w API ani polu pliku.

Render potwierdził 9.09.2026 wdrożenie `4ac315871eab5ca54d0747a62c3595a10b444490`
na web i workerze. Web używa Cloudflare R2, worker nie ma zmiennych `AWS_*`.
Nie sprawdzono polityk dostępu bezpośrednio w Cloudflare i nie zmieniano produkcji.
[Instrukcja konfiguracji i migracji](prywatne-pliki-i-kopie.md) opisuje kolejność,
zakres narzędzia oraz warunki zamknięcia F04. Zależności frontendu i witryny
marketingowej pozostają osobnymi PR-ami.

### Odbiór 2b — aktualizacja z 10.09.2026

PR #40 jest scalony i wdrożony na web oraz workerze. Sprawdzono prywatność
magazynów, zakresy poświadczeń, autoryzację pobierania i rzeczywisty przepływ
syntetycznego pliku przez worker. Szyfrowanie, odczyt i odszyfrowanie syntetycznej
kopii oraz odtworzenie jej relacji w izolowanym PostgreSQL przeszły.
Użytkownik potwierdził zabezpieczenie kopii klucza szyfrowania poza hostingiem.
Odczyt legacy wyłączono; po rozpoznaniu zależności i potwierdzeniu użytkownika
odwołano dwa nieużywane przez SaaS tokeny o nadmiernych uprawnieniach.
Kontrola po odwołaniu potwierdziła zachowany dostęp aplikacji do magazynów.
Szczegółowe dowody infrastruktury pozostają w lokalnym raporcie audytu.

### Etap 2c — kontrola kopii i przygotowanie harmonogramu

Gałąź `codex/audit-backup-monitoring`, wydanie 2.0.1:

- Kopia zdalna zgłasza sukces dopiero po odczycie i porównaniu szyfrogramu.
- `check_backup` wykrywa brak, przekroczony wiek, uszkodzenie i błędny klucz.
  Wiek wynika z podpisanego czasu Fernet; polecenie nie odczytuje bazy danych.
- Osobny przykład konfiguracji zadań kopii i kontroli na Renderze oraz
  [instrukcja wdrożenia i odtwarzania](harmonogram-i-kontrola-kopii.md).
- Test cyklu zdalnej kopii odtwarza syntetyczne dane w PostgreSQL, w tym relacje,
  klucze widgetu, hasła i wektory. Magazyn S3 jest w tym teście atrapą.

Ten etap nie uruchamia usług produkcyjnych. F04 pozostaje częściowo otwarte:
potrzebne są działające harmonogramy i alarmy, niezależne wykrywanie braku
przebiegów, PostgreSQL/PITR, kopie bajtów uploadów oraz pełny restore na stagingu.
Nie jest to odbiór komercyjny całej aplikacji. Po pracach nad kopiami kolejnym
etapem kodu pozostają SSRF, walidacja wejść i atomowe limity kosztów.

### Etap 3b — bezpieczne uploady (F09)

Gałąź `codex/audit-safe-file-uploads`, wydanie 2.0.3, zależne od PR #42:

- Dozwolone formaty i rzeczywista zawartość dokumentów sprawdzane przed zapisem;
  osobne limity odebranych bajtów, rozpakowania, stron i wyodrębnionego tekstu.
- Parser w osobnym procesie z limitami pamięci/czasu, bez sekretów w środowisku;
  globalna blokada na instancję odrzuca równoległy upload z czytelnym 503.
- Logo/awatar: dekodowanie PNG/JPEG/WebP, limity pikseli i zapis oczyszczonego PNG.
- Jedno zlecenie embeddingów po udanym odczycie. Błędy ekstrakcji w tle otrzymują
  `processing_error`/`failed`; przekroczenie limitu wiedzy zachowuje dotychczasową treść.
- Osobna gałąź frontendu `codex/audit-upload-feedback`: informacje o formatach i
  limitach, błędy dostępne dla czytników, ponowienie i polskie statusy dokumentów.

Pierwsze testy przed poprawką odtworzyły 8 niepowodzeń. Regresje obejmują też
rzeczywiste zabicie procesu po timeout, odrzucenie alokacji pamięci, blokadę
między procesami oraz zachowanie przezroczystości/orientacji obrazów.
Wynik końcowej regresji i CI jest zapisany w opisie PR-a.

Wymagana migracja `documents.0015_document_processing_error`. Brak nowych zmiennych
środowiskowych; w tej gałęzi nie zmieniamy produkcji. Szczegółowe limity, odbiór
i ograniczenia opisuje [instrukcja uploadów](bezpieczne-uploady.md). F08 oraz
atomowość limitu wiedzy i cykl życia plików/embeddingów pozostają osobnymi etapami.
