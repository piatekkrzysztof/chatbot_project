# Przegląd końcowy przed oddaniem - 11.11.2026

**Zakres:** backend (`main` w `09f0095`, 2.32.18) i panel z widgetem
(`frontend_chatbot`, `main` w `7823b99`). Cztery niezależne przeglądy kodu
(konta i sesje; widget, czat i dokumenty; płatności, konfiguracja i kopie;
panel i widget), bramki narzędziowe i pełne zestawy testów. Bez działań na
produkcji, bez Stripe live, bez maili.

Ustaleń z [audytu 22.10](audyt-2026-10.md) (P01-P22) i z audytu panelu
(A-01 do A-26) nie powtarzamy - poza tymi, które nadal są otwarte.

**Wynik w jednym akapicie.** Izolacja firm, role, sesje, SSRF, upload,
podpis webhooka i sekrety są w porządku - żaden przegląd nie znalazł dostępu
do cudzych danych. Znalezione usterki to nadużycia publicznego klucza
widgetu, kilka błędów widocznych dla klienta i trzy sprawy rozliczeniowe.
Część jest poprawiona w 2.32.19 (tabela niżej), reszta ma numer R i czeka
w roadmapie - w tym osiem pozycji, które warto zamknąć przed oddaniem.

## Poprawione w tym przeglądzie

Backend 2.32.19, każda pozycja z testem w
`api/tests/test_przeglad_koncowy_2026_11.py` (25 testów pada na 2.32.18).

| Co | Skutek przed poprawką |
|---|---|
| Osobne liczniki limitów dla ruchu widgetu | Jedna osoba z publicznym kluczem, pytając o ustawienia raz na sekundę, zamykała czat firmy; dziesięć razy na sekundę - także panel właściciela. To samo robiło ok. 30 odsłon strony klienta w minucie |
| Dziennik tylko z wpisami znanych osób | Anonimowe żądanie z kluczem widgetu dopisywało wiersze do dziennika cudzej firmy |
| Ograniczniki wiedzy wycinane do skutku | Tekst z dokumentu mógł złożyć ogranicznik bloku albo znacznik braku odpowiedzi |
| pypdf 6.21.4 | 7 podatności, bramka pip-audit czerwona |
| Plan Start do kupienia w okresie próbnym | Karta Start pokazywała „Twój obecny plan" bez przycisku - w trakcie okresu próbnego i po nim |
| Pytanie do modelu raz | Każde pytanie szło do modelu dwa razy (koszt wejścia, krótsza historia) |
| Status stron z witryny | Każda zaimportowana strona wisiała jako „Przetwarzanie" |
| Znaki sterujące w tekście z PDF/DOCX | Błąd 500 przy wgrywaniu i plik bez dokumentu w magazynie |
| Data ostatniego logowania | Ekran Zespół pokazywał „nigdy" przy każdej osobie |
| Rozmowa testowa bez `get_or_create` | Dwa równoczesne żądania zamykały ekran Test bota na stałe |
| Sam znacznik braku jako pusta odpowiedź (ścieżka bez strumienia) | Naliczona wiadomość i pusty tekst |
| 400 zamiast 500 przy złej treści żądania | Lista albo `null` zamiast obiektu, za długi adres, nazwa logowania z samotnym surogatem |

Panel (`frontend_chatbot`): lockfile z poprawionymi undici, zod
i typescript-eslint (bramka audytu była czerwona od 4.11 przez wygasły
wyjątek `braces`; nowy, datowany wyjątek na `minimatch` do 25.11.2026 - bez
poprawionej zgodnej wersji), polskie komunikaty przy błędzie bez treści
i braku sieci (ekrany nie wiszą już na „Wczytuję…" przy 5xx), blokada
podwójnego wczytania `embed.js`, opóźnienie zaczepki 0 nie zamienia się
w 30.

**Po wdrożeniu 2.32.19:** jeden przebieg `ocen_generowanie` (zmienił się
układ wiadomości do modelu) i rzut oka na `/health/`.

## Roadmapa

Status: **potwierdzone** - sprawdziłem ścieżkę w kodzie albo narzędziem;
**z przeglądu** - ustalenie recenzenta z odczytu kodu, bez mojego
niezależnego potwierdzenia ani testu.

### Przed oddaniem klientowi

| ID | Obszar | Ustalenie | Status | Co zrobić |
|---|---|---|---|---|
| R01 | Kopie | Najnowsza pełna kopia ma 1278 h przy progu 744 h; „Kontrola kopii" czerwona od 26.10 (trzy przebiegi z rzędu). To P01 z audytu, starsze o trzy tygodnie | potwierdzone (log GitHub Actions z 9.11) | Właściciel: `backup_full` według [instrukcji](pelna-kopia-i-odtworzenie.md), potem ręczny przebieg monitora |
| R02 | Płatności | Worker w `render.yaml` nie ma żadnej zmiennej `STRIPE_*`, a to on co godzinę uzgadnia płatności. Bez klucza: uzgadnianie nie działa i co godzinę idzie alarm. Z samym kluczem, bez `STRIPE_PRICE_*`: plan po zmianie w portalu wraca co godzinę do planu z chwili zakupu | **Zamknięte 11.11.2026.** Właściciel ustawił zmienne na workerze w Renderze. Kod w 2.32.20: blueprint i `docs/obsluga.md` z `STRIPE_*` dla workera, test spójności obu usług, powiązana subskrypcja z nieznaną ceną zostawia zapisany plan, log i alarm wymieniają brakujące zmienne | - |
| R03 | Płatności | Zakup planu nie zeruje licznika wiadomości: cykl liczy się od założenia okresu próbnego. Firma, która zużyła 2000/2000 w okresie próbnym i kupiła Start, ma martwy widget do miesiąca od rejestracji | **Zamknięte 12.11.2026 w 2.32.21:** licznik zerowany przy pierwszym powiązaniu subskrypcji Stripe z firmą i przy nowym okresie w Stripe, cykl zużycia liczony od początku okresu w Stripe | - |
| R04 | Konto | Właściciel zmienia własny e-mail (`PATCH /api/users/<id>/`) bez hasła, kodu MFA i powiadomienia starego adresu. Przejęty token dostępu wystarcza do przejęcia konta przez reset hasła. To samo pozwala właścicielowi przejąć logowanie pracownika | **Zamknięte 12.11.2026 w 2.32.22:** adres e-mail i nazwa logowania zamknięte do zmian w `PATCH /api/users/<id>/` (panel zmienia tam tylko rolę); odpowiedź nie zdradza cudzych kont | Gdy klient będzie potrzebował zmiany własnego adresu: osobny przepływ z hasłem, MFA, linkiem na nowy adres i wiadomością na stary |
| R05 | Panel | Okres próbny wygląda jak zwykły plan Start: bez słowa o okresie próbnym, bez daty końca; po jego końcu nadal „Asystent aktywny", choć widget odmawia. Przycisk zakupu Start naprawiony w 2.32.19 | **Zamknięte 12.11.2026 w 2.32.23** (panel w osobnym PR): `is_trial`, `trial_ends_at`, `has_access`, `expired` w `billing/plans/`, `has_access`/`is_trial`/`ends_at` na pulpicie; `has_access` liczone tą samą metodą co sprawdzenie w widgecie. Zawieszona subskrypcja też już nie wygląda na działającą | Panel trzeba wdrożyć razem z backendem; bez niego ekran się nie zmienia |
| R06 | Strona główna | Przełącznik „Rocznie −20%" bez ścieżki zakupu (checkout zawsze miesięczny), „rozmowy" w ofercie przy limicie liczonym w wiadomościach, link „Prywatność" prowadzi do ekranu za logowaniem | **Zamknięte 12.11.2026 w panelu (frontend_chatbot#75):** przełącznik roczny zdjęty decyzją właściciela, „wiadomości miesięcznie", stopka prowadzi do https://agencjasm-art.pl/polityka-prywatnosci | Polityka agencji opisuje tylko formularz kontaktowy jej strony - nie chatbota, rozmów odwiedzających ani danych klientów SaaS; treść do uzupełnienia przez właściciela. Rozliczenie roczne: osobna praca (backend rozpoznaje już ceny roczne w webhooku) |
| R07 | Zaproszenia | Brak limitu wysłanych zaproszeń i powtórek na adres; firma bez subskrypcji ma nieograniczoną liczbę miejsc. Mail z naszej domeny z nazwą firmy wybraną przez nadawcę | **Zamknięte 12.11.2026 w 2.32.24:** oczekujące zaproszenia liczą się do miejsc, brak subskrypcji = miejsca planu Start, dzienne pułapy (firma 20, adres 3, ponowna wysyłka 5) w cache z odmową 503 bez cache, bez drugiego oczekującego zaproszenia na adres, nazwa firmy w mailu w jednej linii | Mail nadal podaje nazwę firmy wybraną przez nadawcę - pułapy ograniczają skalę, nie treść |
| R08 | Zaproszenia (A-26) | Stary podgląd `GET /api/accounts/invitations/<klucz>/preview/` i strona panelu `/invite/accept/[token]` miały zniknąć po 30.10.2026 - nadal są | **Zamknięte 12.11.2026 w 2.32.25** (panel w osobnym PR): GET podglądu, trasa, reguła `/preview/` w `TenantMiddleware`, wpis kontraktu (macierz: 97 operacji) i pole `email` w schemacie usunięte; w panelu strona `/invite/accept/[token]` i gałąź `tokenZeSciezki` | Panel wdrożyć przed backendem albo razem z nim |

### W pierwszych tygodniach

| ID | Obszar | Ustalenie | Status |
|---|---|---|---|
| R09 | Płatności | Odrzucone przez Stripe pierwsze utworzenie sesji zostawia zablokowaną próbę zakupu bez wyjścia (zapisane parametry, brak `sesja_id`, po 23 h trwałe 503) | **Zamknięte 12.11.2026 w 2.32.26:** odrzucenie 400/404 zamyka próbę; niepewne odpowiedzi bez zmian |
| R10 | Koszty | Czat testowy nie sprawdza subskrypcji: 100 odpowiedzi dziennie bez planu, bez końca. Ta sama klasa: ręczne odświeżenie źródła i upload bez ważnego planu | **Zamknięte 13.11.2026 w 2.32.27** (decyzja właściciela: blokada): czat testowy, upload, dodanie i ręczne odświeżenie strony bez ważnego planu - 402; panel pokazuje powód w teście bota |
| R11 | Płatności | `stripe_customer_id` nie jest uzupełniany, gdy klienta założył sam Stripe - płacąca firma bez dostępu do portalu | **Zamknięte 13.11.2026 w 2.32.28:** synchronizacja aktywnej subskrypcji zapisuje jej `customer` przy firmie (tylko gdy metadane wskazują tę firmę) |
| R12 | MFA | Logowanie do panelu administracyjnego Django bez dobowego limitu kodów i bez maila z ostrzeżeniem (reszta P16) | **Zamknięte 13.11.2026 w 2.32.29:** logowanie admina liczy błędne kody do wspólnego dobowego licznika z panelem (20, mail, blokada do zmiany hasła) |
| R13 | Źródła WWW | Przekierowanie `firma.pl` ↔ `www.firma.pl`: importuje się tylko strona główna, status zielony | **Zamknięte 13.11.2026 w 2.32.30:** `www.` i domena bez `www` to jedna witryna przy linkach, mapie strony i imporcie; strona główna nie dubluje się w dwóch pisowniach; inne subdomeny dalej osobno |
| R14 | Pamięć | FAQ bez limitu długości; czat wczytuje do 500 pełnych wpisów na wiadomość. Teksty widgetu (powitanie, zaczepki) bez limitów | **Zamknięte 13.11.2026 w 2.32.31:** granice zapisu z panelu (FAQ: pytanie 500, odpowiedź 4000; powitanie i pytania startowe po 1000; zaczepka 200 i tylko obsługiwane języki); czat czyta odpowiedzi tylko wybranych wpisów |
| R15 | Panel | Ustawienie „Pozycja" widgetu nie ma żadnego skutku (skrypt czyta tylko atrybut `data-position`) | **Zamknięte 13.11.2026 w panelu (frontend_chatbot#79):** `embed.js` bierze pozycję z ustawień widgetu; atrybut `data-position` na stronie klienta ma pierwszeństwo |
| R16 | Widget | Przy nieudanym odczycie ustawień widget firmy z własną marką pokazuje „SM-art" do końca odsłony | **Zamknięte 13.11.2026 w panelu (frontend_chatbot#80):** ostatnie udane ustawienia są zapamiętywane, odczyt ponawiany dwa razy, a bez ustawień okno jest bez podpisu („Czat", bez stopki) |
| R17 | Konto | Rejestracja zdradza, czy adres ma konto (400 zamiast 202); nazwa użytkownika może być cudzym adresem e-mail i blokuje tej osobie rejestrację | **Zamknięte 14.11.2026 w 2.32.32:** początek rejestracji odpowiada 202 także dla adresu z kontem (osoba dostaje mail „masz już konto", najwyżej raz na dobę); nazwa z `@` musi być własnym adresem konta; wcześniej zajęta nazwa nie blokuje rejestracji |
| R18 | Widget | Wysłanie pytania przed wczytaniem zapisanej historii gubi je z ekranu; usunięcie ostatniego wiersza ostatniej strony listy pokazuje błąd i stary wiersz | **Zamknięte 14.11.2026 w panelu (frontend_chatbot#81):** pytanie czeka na wczytanie zapisanej rozmowy; Konwersacje i Baza wiedzy po 404 cofają się o stronę |

### Niskie i porządki

- ~~Strumień przerwany w połowie kończy się zwykłym `done` bez znacznika
  urwania; awaria modelu przy trafionych fragmentach zapisuje źródło
  „document".~~ **Zamknięte w 2.32.34:** `done` niesie `przerwana: true`,
  a awaria modelu liczy się jako brak odpowiedzi.
- ~~`acks_late` z `reject_on_worker_lost` bez limitu doręczeń: dokument, który
  zabija proces, blokowałby jedyny worker.~~ **Zamknięte w 2.32.33:** po
  trzech przerwanych doręczeniach dokument dostaje błąd i zadanie odpuszcza.
- ~~Adres podstrony dłuższy niż 200 znaków kończy import surowym błędem bazy.~~
  **Zamknięte w 2.32.33:** pomijany ze zwykłym komunikatem.
- ~~Diagnostyka zadań pokazuje każdemu członkowi firmy nazwy hostów workera.~~
  **Zamknięte w 2.32.33:** nazwy i treść błędu brokera tylko dla obsługi.
- ~~`DEFAULT_PERMISSION_CLASSES` nieustawione (dziś każdy widok ustawia
  uprawnienia sam, pilnuje tego kontrakt dostępu); przeglądalne API włączone
  w produkcji.~~ **Zamknięte w 2.32.33:** domyślnie wymagane logowanie,
  API odpowiada tylko JSON-em.
- Puste `STRIPE_WEBHOOK_SECRET`, `DATABASE_URL`, `FRONTEND_URL` i `REDIS_URL`
  mają ciche wartości domyślne - sprawdzenia przy starcie tylko ostrzegają.
- CI: bramka ruff może przejść jałowo, brak bloku `permissions:`, akcje
  przypięte znacznikiem, wejście monitora kopii wstawiane wprost do polecenia.
- `/health/` ~~otwiera połączenie z brokerem przy każdym żądaniu~~ i podaje
  dokładną wersję. **Połączenie zamknięte w 2.32.33** (wynik pamiętany 15 s).
  Wersja zostaje świadomie: to jedyna odpowiedź na pytanie „co jest na
  produkcji" (opis w `chatbot_project/zdrowie.py`).
- Pełna kopia ma sztywny limit 100 MiB razem z wektorami - przy kilkunastu
  tysiącach fragmentów przestanie się mieścić.
- ~~Alarm uzgadniania Stripe po pojedynczym błędzie sieci.~~ **Zamknięte
  w 2.32.34:** pierwszy błąd sieci albo limitu jest ponawiany, alarm po
  powtórce.
- ~~`.env.dev` w repozytorium (martwy), `.gitignore` nie obejmuje `.env.*`~~
  (**zamknięte 13.11.2026 w PR #196**), pusty `runtime.txt`.
- ~~Limit logowania na konto liczony po wpisanym tekście, nie po koncie
  (osobne liczniki dla nazwy i adresu).~~ **Zamknięte w 2.32.34:** jeden
  licznik na konto.
- Panel: błędy pól jako surowy JSON, brak `maxLength` w polu czatu, pole
  logowania typu `email` przy dowolnych nazwach użytkowników, odwołanie
  zaproszenia jednym kliknięciem, stan MFA nieodświeżany po zmianie na tym
  samym ekranie, `powrot` bez parametrów zapytania.

### Nadal otwarte z audytu 22.10 (decyzje właściciela)

P04 limity źródeł WWW, P05 branding po obniżce planu, P06 wiązanie klucza
widgetu z witryną (zamyka też resztę ryzyka z liczników - atak z wielu
adresów), pułap maili z zapytaniami (P03), P18 hasło lokalnej bazy,
A-07 osobna domena widgetu.

## Czego nie dało się sprawdzić z repozytorium

- Rzeczywiste zmienne środowiska w Renderze na web i workerze (R02,
  `TRUSTED_PROXY_DEPTH`, `REDIS_URL`, `BACKUP_ENCRYPTION_KEY`).
- Ustawienia panelu Stripe: subskrybowane zdarzenia, wynik nieudanych
  płatności, zwroty i spory.
- Ochrona gałęzi i wymagane sprawdzenia na GitHubie.
- Czy przed aplikacją stoi limit żądań albo pamięć podręczna (Cloudflare).

## Wyniki bramek

| Bramka | Wynik |
|---|---|
| Backend, pełny zestaw na stanie końcowym (lokalnie, baza `saas_restore_*`) | 3118 zaliczonych, 0 niezaliczonych |
| Backend, nowe testy na kodzie 2.32.18 | 25 z 31 pada (pozostałe 6 to testy kontrolne) |
| `manage.py check`, `makemigrations --check` | bez uwag |
| pip-audit | 0 po podbiciu pypdf (było 7) |
| bandit | 0 średnich i wysokich |
| Panel: Vitest | 335 zaliczonych |
| Panel: Playwright | 123 zaliczone |
| Panel: lint, `tsc`, build | czyste |
| Panel: audyt zależności | zielony z jednym datowanym wyjątkiem (`minimatch`, do 25.11.2026) |
