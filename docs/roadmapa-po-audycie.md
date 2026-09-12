# Roadmapa napraw po audycie SaaS

Data rozpoczęcia: 9.09.2026. **Aktualizacja: 12.09.2026, PR #49 scalony i wdrożony. F15 część 2: backend #50 i panel #13.**
Ta lista obejmuje wszystkie 25 grup ustaleń. Osobno wskazujemy scalony kod,
potwierdzone wdrożenie i pozostały odbiór operacyjny. Historia niżej zachowuje
wyniki z dnia danego etapu; bieżący status określają poniższe tabele.

Budżet: korzystamy z obecnych zasobów Rendera i R2. Nie planujemy nowych
płatnych workerów, cronów ani instancji bazy bez osobnej decyzji właściciela.

Zasada realizacji: odtworzenie błędu → poprawka → test regresyjny → kontrola
powiązanych przepływów → zapis wyniku. Zmiany dostępu, pieniędzy i retencji
sprawdzamy także przy równoległych operacjach i po awarii.

## Kolejność i warunki odbioru

| Etap | Ustalenia | Zakres i warunek odbioru | Status |
|---|---|---|---|
| 1. Izolacja i role | F01, F02, F03 | JWT/klucz/role/metody nie umożliwiają przekroczenia granicy firmy; brak samodzielnego awansu i utraty ostatniego właściciela; CSV działa na własnej firmie bez klucza widgetu | PR #38 scalony; Render potwierdził wdrożenie na web i workerze |
| 2. Prywatność i ochrona danych | F04, F05, F12, F13 | Prywatny storage dokumentów/kopii, podpisane odczyty i szyfrowanie; bezpieczna retencja, Docker i zależności | PR #39–#41 scalone; prywatny storage i niezależny klucz kopii sprawdzone. PITR instancji dostępny. Nadal: alarmy/harmonogramy kopii, pełny restore SaaS z plikami i zależności frontendu |
| 3. Bezpieczne wejścia i koszty | F06, F08, F09, F23 | SSRF, upload, rezerwacje wiadomości, odporne formularze | Backend #42–#44 oraz frontend #11 scalone. Backend web live na `e5259ce` (F08). Strona marketingowa #1 live na `43a36d0`; rzeczywista wiadomość przeszła kolejkę i SMTP, właściciel potwierdził odbiór. Nadal: odbiór uploadu, kontrola rezerwacji/alertów i końcowy odbiór F23 opisany niżej |
| 4. Konta i sesje | F07, F14, F15; reset hasła z F22 | Walidacja haseł, adresów i zaproszeń; atomowe miejsca/kody; MFA admina; prawidłowe cookies/CSRF; bezpieczne odzyskiwanie konta | F07, MFA #48 i cookies/CSRF #49 scalone; web/worker live `a4ad183` (2.0.8). Atomowa rotacja i wiele kart w backendzie #50 i panelu #13. Nadal: odbiór poczty/retencji, świeże hasło przy MFA, odwoływanie sesji i reset |
| 5. Wiedza i cykl życia danych | F10, F17, F18, F19, F25 | Kompletny import, atomowa publikacja embeddingów i usuwanie pochodnych, poprawne CSV i feedback, wyszukiwanie FAQ i regresja RAG | Do wykonania |
| 6. Płatności | F11; status płatności z F22 | Idempotencja Checkout/webhooków, identyfikatory i okresy Stripe, retry/uzgadnianie; UI potwierdza konkretny zakup | Do wykonania |
| 7. Wydajność i obsługa | F16, F20, F21, F24; pozostałe F22 | Paginacja/N+1, SLO, dziennik i minimalizacja danych, alarmy/kopie/restore, obowiązkowe bramki CI, pełne stany UI | Do wykonania |
| 8. Odbiór komercyjny | Wszystkie | Staging zgodny z produkcją, negatywne testy dostępu, przegląd infrastruktury, obciążenie, odtworzenie kopii, płatności testowe, onboarding i dostępność | Do wykonania |

## Najbliższa kolejność prac

1. **Domknąć odbiór już wdrożonych zmian.** Ustalić prawdziwy adres klienta
   za proxy i sprawdzić odporność na podrobione nagłówki także po ewentualnej
   zmianie ustawień. Przeprowadzić pełny test formularza z Turnstile w przeglądarce.
   Podłączyć kontrolę kolejki, kopii i rezerwacji do alarmów na obecnych zasobach;
   sprawdzić, że brak kolejnego przebiegu też wywołuje alarm. Odtworzyć dane i pliki
   w izolacji oraz zapisać zmierzone RPO/RTO. Dostępny PITR nie zastępuje testu restore.
2. **F07 część 2 scalona.** Backend #47 i panel #12 po merge. Read-only Render
   potwierdził web i worker live na `7236475`. Nadal wymagany rzeczywisty odbiór
   poczty aktywacyjnej, kontrola wdrożenia panelu i harmonogram retencji zgłoszeń
   na obecnych zasobach. Instrukcja: [aktywacja konta](aktywacja-konta.md).
3. **MFA #48 wdrożone; teraz F15 i odzyskiwanie konta.** Obowiązkowy drugi składnik
   admina, atomowe kody/bilety, limity i szyfrowanie działają na web i workerze.
   Właściciel zabezpieczył DJANGO_SECRET_KEY; test HTTPS z syntetycznym kontem
   zaliczony, konto usunięte. Po merge przywrócono automatyczne wdrożenia obu usług.
   Cookies/CSRF #49 już wdrożone. Bieżąca część: atomowa rotacja w #50 i wiele kart
   w panelu #13; [kolejność wdrożenia](rotacja-sesji.md): panel przed backendem.
   Panel #13 usuwa również cztery zgłoszenia npm audit; wynik po poprawce: 0.
   Potem odwoływanie rodzin tokenów/access JWT, reset hasła i świeże hasło przy MFA.
4. **F10/F17/F18/F19/F25 — wiedza i RAG.** Import wszystkich formatów, idempotentne
   zadania, atomowa publikacja i usuwanie plików/embeddingów, bezpieczne CSV,
   poprawność feedbacku, wyszukiwanie FAQ i regresja jakości/izolacji.
5. **F11 i płatności z F22.** Idempotencja Checkout/webhooków, okresy subskrypcji,
   uzgadnianie błędów i jednoznaczny status konkretnego zakupu. Testy w trybie
   testowym Stripe; brak rzeczywistych obciążeń bez osobnej zgody.
6. **F12/F16/F20–F22/F24 — utrzymanie i UX.** Dokończenie zależności frontendu,
   paginacja/N+1, log zdarzeń i minimalizacja danych, obowiązkowe kontrole CI,
   onboarding i komplet stanów ładowania/błędów/pustych danych.
7. **Odbiór komercyjny.** Pełny negatywny test dostępu, obciążenie, restore,
   onboarding, dostępność i płatności testowe w środowisku zgodnym z produkcją.

P1 dotyczące kont, administracji i płatności nadal blokują deklarację gotowości
komercyjnej. Sukces wdrożenia formularza nie zamyka audytu całego SaaS.

## Rejestr wszystkich ustaleń — stan 11.09.2026

| ID | Stan i dowód | Co pozostaje do odbioru lub naprawy |
|---|---|---|
| F01 | Naprawa scalona i wdrożona, backend #38 | Końcowa macierz dostępu przy odbiorze komercyjnym |
| F02 | Naprawa ról i ostatniego właściciela, #38 | Atomowe przyjmowanie zaproszeń należy do F07 |
| F03 | Izolacja CSV naprawiona, #38 | Integralność treści CSV pozostaje w F19 |
| F04 | Prywatne magazyny, szyfrowane kopie i klucz poza hostingiem; #40/#41 | Harmonogram/alerty, pełna kopia plików i restore SaaS |
| F05 | Bezpieczny kontekst/obraz, #39 | Końcowy skan używanego obrazu |
| F06 | SSRF, DNS i limity crawlera naprawione, #42 | Odbiór integracji w pełnym przepływie importu |
| F07 | Backend #46/#47 i panel #12 scalone; backend web/worker live 7236475 | Kontrola wdrożenia panelu i odbiór SMTP; retencja/alerty zgłoszeń, IP za proxy i ocena nadużyć przez wiele skrzynek/aliasów |
| F08 | Rezerwacje i rozliczenie SSE, #44; web live `e5259ce` | Kontrola wdrożenia workera, alarmy i uzgadnianie wygasłych rezerwacji; pomiar kosztów |
| F09 | Backend #43 i panel #11 scalone | Produkcyjny odbiór uploadu na wydzielonej firmie |
| F10 | Otwarte; F09 poprawił część walidacji plików | Pełny proces budowy wiedzy i wszystkie formaty |
| F11 | Otwarte | Spójność i idempotencja płatności oraz webhooków |
| F12 | DRF i strona poprawione; panel #13 aktualizuje Next.js do 16.3.5, sharp do 0.35.4 i zależności pośrednie; npm audit: 4 zgłoszenia → 0 | CI i wdrożenie panelu #13; ponowne skany całości przed wydaniem |
| F13 | Retencja aktywnych rozmów naprawiona, #39 | Końcowy odbiór polityki retencji |
| F14 | #48 scalony i wdrożony, migracja 0035 oraz rzeczywiste logowanie API/admin z MFA sprawdzone; CI 1606 testów, 87,50% pokrycia | Rotacja/retencja operacyjna, świeże hasło przy konfiguracji i odzyskiwanie MFA |
| F15 | #49 scalony i web/worker live na `a4ad183`; cookies/Origin/no-store. Część 2: atomowa rotacja i koordynacja kart przygotowane, [instrukcja](rotacja-sesji.md) | CI i wdrożenie części 2; odwoływanie rodzin tokenów/access JWT, zmiana hasła i odzyskiwanie konta |
| F16 | Otwarte | Paginacja, N+1, pomiary opóźnień i obciążenia |
| F17 | Otwarte | Powtarzalne zadania i atomowa publikacja embeddingów |
| F18 | Otwarte | Spójne usuwanie i limity wiedzy/plików/pochodnych |
| F19 | Otwarte | Transakcyjne CSV, formuły w eksportach i integralność ocen |
| F20 | Otwarte | Kompletność dziennika, minimalizacja i przepływy danych |
| F21 | Kontrola kopii #41, dostępny PITR; 11.09 odtworzono zaszyfrowany snapshot danych aplikacji (745 obiektów) i sprawdzono migrację/rollback MFA | Działające alarmy, brak przebiegów, pełny restore z bajtami plików, RPO/RTO i instrukcja incydentowa |
| F22 | Otwarte; poprawiono komunikaty uploadu i formularza | Reset hasła, stan zakupu, onboarding i pozostałe stany panelu |
| F23 | Kod #1 strony wdrożony; test SMTP i odbiór w skrzynce zaliczone | Pełny E2E Turnstile, rzeczywiste IP za proxy, alerty i docelowy proces backup/restore |
| F24 | Częściowo: rozszerzone testy i aktualizacja roadmapy | Obowiązkowe bramki repozytoriów, istniejący dług lint/typecheck, zgodność dokumentacji |
| F25 | Otwarte | FAQ poza pierwszą dwudziestką, rozdzielenie instrukcji i treści, regresja RAG |

## Odbiór MFA i kopii danych — 11.09.2026

- PR #48 scalony jako `1c4bad7`; jego drzewo jest identyczne z wdrożonym `3a2e84d`.
- Web `dep-dai4k63m8hqs738oqjeg` i worker `dep-dai4k6dg1s2s73celltg`: live.
  Migracja `accounts.0035` potwierdzona. Okno serwisowe trwało około 3 minuty 4 s.
  Automatyczne wdrożenia obu usług przywrócono po merge.
- Przed wdrożeniem wykonano zaszyfrowany snapshot danych aplikacji do istniejącego
  prywatnego R2: 745 obiektów, 3 676 506 bajtów szyfrogramu. Odczyt kopii,
  lokalny restore, migracja i jej rollback przeszły; tymczasową bazę usunięto.
  Snapshot nie zawiera bajtów dokumentów/uploadów i nie zamyka pełnego restore SaaS.
- Test HTTPS sprawdził szyfrogram sekretu w DB, brak JWT przed drugim krokiem,
  sukces TOTP, odmowę replay biletu, blokadę admina samym hasłem, kod zapasowy
  admina oraz zwykłe logowanie bez MFA. Syntetyczne rekordy posprzątano.
- Kopie DJANGO_SECRET_KEY i osobnego BACKUP_ENCRYPTION_KEY właściciel potwierdził
  poza hostingiem. Wartości sekretów nie należą do dokumentacji ani repozytorium.

## Odbiór F23 i infrastruktury — 11.09.2026

- Strona [PR #1](https://github.com/piatekkrzysztof/sm-art-agencja/pull/1),
  commit `43a36d0e789c12566b15f8e03b000bf88c255bf1`, deploy
  `dep-dahs9vifngtc73ds1kq0`: live. Proces web i worker współdzielą istniejącą
  usługę. Nowa baza logiczna nie jest nową płatną instancją.
- CI strony: 72 testy, 95,40% pokrycia; Ruff, Bandit i pip-audit zaliczone.
  CI backendu #44: 1525 testów, 87,03% pokrycia; dowody w opisach PR-ów.
- Produkcja: 14 tras HTTP 200; bezpieczne cookie i no-store; nieważny podpis
  formularza oraz obcy Origin odrzucane (403), błędne pola (422), zbyt duże
  żądanie (413). Wpisane wartości po błędzie walidacji pozostają.
- Testowy rekord przeszedł prawdziwą kolejkę i worker: `sent`, jedna próba,
  brak błędu. Właściciel potwierdził odbiór w skrzynce, poza spamem.
  Rekord dodano bezpośrednio do kolejki: to dowód dostawy, a nie pełnego
  przejścia publicznego formularza z produkcyjnym Turnstile.
- Oba konta runtime logują się do nowej bazy; brak uprawnień do tabel SaaS.
  Heartbeat aktualny, brak failed/overdue/queued po teście.
- `CONTACT_PROXY_HOPS=0`: podrobiony X-Forwarded-For nie steruje kluczem limitu.
  Nie potwierdzono jeszcze, że klucz odpowiada rzeczywistemu użytkownikowi:
  wspólny adres proxy może powodować wspólny limit 5 prób/godzinę. Nie należy
  przełączać na 1 bez sprawdzenia rzeczywistego łańcucha proxy.
- API Rendera potwierdziło PITR `AVAILABLE` od `2026-09-07T04:44:50Z`.
  [Dokumentacja odzyskiwania](https://render.com/docs/postgresql-backups)
  opisuje mechanizm instancji, ale samo API nie dowodzi udanego odtworzenia.
  Eksport jednej logicznej bazy SaaS nie jest kopią nowej bazy formularza.
- Rzeczywisty `pg_dump` nowej bazy wykonano ze spójnego snapshotu po potwierdzeniu,
  że outbox zawiera tylko oznaczoną wiadomość testową. **Lokalny restore przeszedł**:
  trzy tabele, pięć indeksów, ograniczenia outboxa, identyczne payload/digest/status
  i liczba prób testowej wiadomości. PostgreSQL źródłowy 16, klient dump/restore 17,
  lokalny serwer 15; pominięto tylko nieobsługiwane lokalnie `SET transaction_timeout=0`.
  Lokalny serwer zatrzymano. Próba nie obejmowała odtworzenia ról/grantów, PITR
  dostawcy ani pełnego SaaS z plikami; odbiór na identycznej wersji pozostaje otwarty.
- W odczytanej liście usług Rendera nie ma zadań cron kopii/kontroli, strona
  nie ma health-check path ani rozpoznanych zmiennych zewnętrznego monitora.
  Nie wyklucza to monitora poza Renderem. Sam `contact-check` i logi nie dowodzą
  działającego alarmowania; wymagany jest kontrolowany test alarmu i jego odbioru.

## F07 część 2 — potwierdzenie skrzynki i panel

Gałęzie `codex/audit-email-activation` w backendzie i panelu, backend 2.0.6.
Migracja dodaje tylko tabelę zgłoszeń; nie odbiera dostępu istniejącym kontom.
Hasło nie jest przechowywane przed potwierdzeniem, a konto, firma i trial
powstają atomowo przy aktywacji. Logowanie zachowuje spacje w haśle.

Testy obejmują przejęcie adresu pomiędzy krokami, dwa równoczesne potwierdzenia,
wygaśnięcie, rotację tokena, awarię SMTP i bazy, brak triala przed potwierdzeniem,
limity wiadomości, retencję oraz dostępność i prywatność linku w przeglądarce.
Końcowe wyniki zapisujemy w opisach PR-ów.

Panel już wysyłał `max_users=1` i nie udostępniał wyboru wielu użyć; wcześniejsze
zadanie usunięcia tego wyboru było nieaktualne. Teraz adresat zaproszenia jest
pokazywany tylko do odczytu. Produkcji nie zmieniano. Automatyczny harmonogram
retencji i rzeczywiste dostarczenie nowej wiadomości wymagają osobnego odbioru.

## F07 część 1 — przygotowanie backendu (historia)

Gałąź `codex/audit-registration-invitations`, wersja 2.0.5.
[Kontrakt API i instrukcja migracji](rejestracja-i-zaproszenia.md) opisują
jednorazowe zaproszenia, limity i zależność od istniejącego Redisa.
Migracja `accounts.0033_unique_account_email` odmawia wykonania przy konflikcie
adresów; nie scala ani nie usuwa kont. Odczyt kontrolny produkcji 11.09.2026
wykazał zero grup duplikatów oraz zero zaproszeń bez adresata lub z limitem
większym niż jeden. Nie wykonywano migracji ani wdrożenia na produkcji.

Przed poprawką 17 nowych przypadków odtworzyło błędy. Końcowy wynik regresji
i CI zapisujemy w opisie PR-a. Testy używają syntetycznych danych i lokalnego
PostgreSQL; obejmują też odmowę migracji przy duplikatach, awarię licznika prób
oraz rollback konta, firmy i subskrypcji. F07 pozostaje otwarte do ukończenia
weryfikacji skrzynki, panelu i odbioru całego przepływu.

## Historia etapów (statusy na dzień danego wpisu)

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
