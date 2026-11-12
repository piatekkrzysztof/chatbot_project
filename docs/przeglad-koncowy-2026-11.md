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
| R05 | Panel | Okres próbny wygląda jak zwykły plan Start: bez słowa o okresie próbnym, bez daty końca; po jego końcu nadal „Asystent aktywny", choć widget odmawia. Przycisk zakupu Start naprawiony w 2.32.19 | potwierdzone po stronie API | Backend: `is_trial`/`expired` w odpowiedzi; panel: etykieta, data i stan na pulpicie |
| R06 | Strona główna | Przełącznik „Rocznie −20%" bez ścieżki zakupu (checkout zawsze miesięczny), „rozmowy" w ofercie przy limicie liczonym w wiadomościach, link „Prywatność" prowadzi do ekranu za logowaniem | z przeglądu | Decyzja właściciela: zdjąć albo wdrożyć rozliczenie roczne; poprawić słowo i link |
| R07 | Zaproszenia | Brak limitu wysłanych zaproszeń i powtórek na adres; firma bez subskrypcji ma nieograniczoną liczbę miejsc. Mail z naszej domeny z nazwą firmy wybraną przez nadawcę | z przeglądu | Liczyć oczekujące zaproszenia do limitu miejsc, brak subskrypcji = najniższy plan, dzienny pułap |
| R08 | Zaproszenia (A-26) | Stary podgląd `GET /api/accounts/invitations/<klucz>/preview/` i strona panelu `/invite/accept/[token]` miały zniknąć po 30.10.2026 - nadal są | potwierdzone | Usunąć widok, trasę, regułę w `TenantMiddleware`, wpis kontraktu, przegenerować macierz; w panelu stronę i gałąź `tokenZeSciezki` |

### W pierwszych tygodniach

| ID | Obszar | Ustalenie | Status |
|---|---|---|---|
| R09 | Płatności | Odrzucone przez Stripe pierwsze utworzenie sesji zostawia zablokowaną próbę zakupu bez wyjścia (zapisane parametry, brak `sesja_id`, po 23 h trwałe 503) | z przeglądu |
| R10 | Koszty | Czat testowy nie sprawdza subskrypcji: 100 odpowiedzi dziennie bez planu, bez końca. Ta sama klasa: ręczne odświeżenie źródła i upload bez ważnego planu | potwierdzone (`message_quota.py`); decyzja właściciela |
| R11 | Płatności | `stripe_customer_id` nie jest uzupełniany, gdy klienta założył sam Stripe - płacąca firma bez dostępu do portalu | z przeglądu |
| R12 | MFA | Logowanie do panelu administracyjnego Django bez dobowego limitu kodów i bez maila z ostrzeżeniem (reszta P16) | z przeglądu |
| R13 | Źródła WWW | Przekierowanie `firma.pl` ↔ `www.firma.pl`: importuje się tylko strona główna, status zielony | potwierdzone (`same_site` porównuje z adresem wpisanym) |
| R14 | Pamięć | FAQ bez limitu długości; czat wczytuje do 500 pełnych wpisów na wiadomość. Teksty widgetu (powitanie, zaczepki) bez limitów | potwierdzone (serializer) |
| R15 | Panel | Ustawienie „Pozycja" widgetu nie ma żadnego skutku (skrypt czyta tylko atrybut `data-position`) | z przeglądu |
| R16 | Widget | Przy nieudanym odczycie ustawień widget firmy z własną marką pokazuje „SM-art" do końca odsłony | z przeglądu |
| R17 | Konto | Rejestracja zdradza, czy adres ma konto (400 zamiast 202); nazwa użytkownika może być cudzym adresem e-mail i blokuje tej osobie rejestrację | z przeglądu |
| R18 | Widget | Wysłanie pytania przed wczytaniem zapisanej historii gubi je z ekranu; usunięcie ostatniego wiersza ostatniej strony listy pokazuje błąd i stary wiersz | z przeglądu |

### Niskie i porządki

- Strumień przerwany w połowie kończy się zwykłym `done` bez znacznika
  urwania; awaria modelu przy trafionych fragmentach zapisuje źródło
  „document".
- `acks_late` z `reject_on_worker_lost` bez limitu doręczeń: dokument, który
  zabija proces, blokowałby jedyny worker.
- Adres podstrony dłuższy niż 200 znaków kończy import surowym błędem bazy.
- Diagnostyka zadań pokazuje każdemu członkowi firmy nazwy hostów workera.
- `DEFAULT_PERMISSION_CLASSES` nieustawione (dziś każdy widok ustawia
  uprawnienia sam, pilnuje tego kontrakt dostępu); przeglądalne API włączone
  w produkcji.
- Puste `STRIPE_WEBHOOK_SECRET`, `DATABASE_URL`, `FRONTEND_URL` i `REDIS_URL`
  mają ciche wartości domyślne - sprawdzenia przy starcie tylko ostrzegają.
- CI: bramka ruff może przejść jałowo, brak bloku `permissions:`, akcje
  przypięte znacznikiem, wejście monitora kopii wstawiane wprost do polecenia.
- `/health/` otwiera połączenie z brokerem przy każdym żądaniu i podaje
  dokładną wersję.
- Pełna kopia ma sztywny limit 100 MiB razem z wektorami - przy kilkunastu
  tysiącach fragmentów przestanie się mieścić.
- Alarm uzgadniania Stripe po pojedynczym błędzie sieci.
- `.env.dev` w repozytorium (martwy), `.gitignore` nie obejmuje `.env.*`,
  pusty `runtime.txt`.
- Limit logowania na konto liczony po wpisanym tekście, nie po koncie
  (osobne liczniki dla nazwy i adresu).
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
