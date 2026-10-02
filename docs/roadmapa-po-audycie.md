# Roadmapa napraw po audycie SaaS

## Ponowny audyt 30.09.2026 - bieżące naprawy

Nie powtarzamy już odebranych etapów. Nowe przypadki awarii mają osobne ID:

| ID | Zakres | Stan |
|---|---|---|
| A01 | Dwie otwarte sesje zakupu jednego abonamentu | Poprawka wdrożona, migracja 0041 potwierdzona 1.10. 2.10 zaliczono rzeczywisty Stripe test mode: powtórzenia, utrata odpowiedzi create/expire, błąd zapisu ID, operator, konkurencyjne plany i blokada po opłaceniu bez webhooka. Otwarte: dodatkowe wyścigi, dawne sesje po migracji i panel. [Protokół](odbior-a01-a02-2026-10-02.md) |
| A02 | Starsza synchronizacja Stripe nadpisuje nowszą | Poprawka wdrożona, migracja 0042 potwierdzona 1.10. 2.10 zaliczono Stripe test mode: odzyskanie bez webhooka, serializacja synchronizacji, replay starego zdarzenia, anulowanie, odnowienie, past_due i odzyskanie po zapłacie. Alarm sprawdzony tylko lokalnie; nadal transport webhooków, rzeczywisty worker/Beat, skrzynki i UI. [Protokół](odbior-a01-a02-2026-10-02.md) |
| A03 | Zapis promptu równoległy z usunięciem rozmowy | Backend 2.19.3 wdrożony; accounts.0043 i chat.0008 potwierdzone 1.10. [Odbiór panelu/widgetu, 410/SSE i równoległego usuwania](usuwanie-rozmow-a03.md) pozostaje otwarty |
| A04 | Plik bez rekordu po awarii magazynu | R2: 9 plików i ochrona współdzielenia odebrane 1.10; 2.19.7 i 2.19.8 wdrożone. 2.10 potwierdzono powiadomienia UptimeRobot down/up. Zaliczono awarie procesów/TCP/HTTP, zatrzymanie lokalnego workera na ponad 180 s, restart Redis oraz syntetyczny restore z kwarantanną wszystkich niedokończonych zleceń. Nadal: odbiór alarmu aplikacji nr 22 na obu skrzynkach, zewnętrzny test wykrycia awarii i kontrola aktualnej kopii produkcji. [Protokół i granice](odbior-a04-awarie-2026-10-02.md) |
| A05 | Niewykonalny okres retencji przyjmowany przez API | Poprawka wdrożona z A03; migracje i kontrola wszystkich istniejących okresów (0–3650) potwierdzone 1.10. Odbiór błędnych/granicznych wartości przez API pozostaje otwarty |

### A04: historia przygotowania kodu

1. Odtworzono utratę callbacku usuwania oraz przedwczesne usunięcie starego
   logo przy nieudanym zapisie nowego.
2. Dodano trwały rejestr w transakcji zmiany danych, obsługę kaskady firmy
   i wymiany plików; błędny zapis rejestru wycofuje zmianę.
3. Dodano odzyskiwanie przez obecny worker/Beat, ograniczone ponowienia,
   dzierżawy oraz ochronę przed potwierdzeniem cudzej próby.
4. Zabezpieczono zmianę celu magazynu, współdzielone pliki i równoległe
   wymiany; logi i alarmy nie zawierają nazw obiektów ani sekretów.
5. Dodano raport operatora, jawne ponowienie i wstrzymanie niezakończonych
   zleceń podczas izolowanego odtwarzania kopii.
6. Przygotowano migracje i instrukcję odbioru. Wyniki testów i CI są w PR;
   w tym etapie nie zmieniano produkcji.

### Raport kontrolny po A04 — 2.19.5

Przygotowano [raport plików bez odwołania](raport-plikow-bez-odwolania.md):
odczyt metadanych bez kasowania, bez pobierania treści i bez tworzenia zleceń.
Rozróżnia pliki używane, świeże uploady, stany A04 i kandydatów do sprawdzenia.
Ograniczenia lub błędy oznaczają niepełny wynik, domyślnie bez nazw plików.
Historia F18 i kontrola z 17.09 pozostają ważne; nowe narzędzie nie jest
stwierdzeniem, że na produkcji znaleziono sieroty. **Raport wykonany 30.09.2026:**
1 prywatny dokument powiązany z bazą (187 805 B), 0 obiektów w sprawdzonych
prefiksach default, 0 kandydatów do wyjaśnienia i pełny zakres obu skanów.
Nie kasowano plików. [Wyniki i granice odbioru](odbior-operacyjny-2026-10-01.md).

**Dalej:** A03/A05 w panelu/widgecie; równolegle domknąć transport webhooków, harmonogram, alarmy i pozostałe próby A01/A02 opisane w [protokole Stripe](odbior-a01-a02-2026-10-02.md). Poprawka pypdf 2.19.9 jest scalona (#117), a publiczny `/health/` potwierdził wdrożenie 2.10.
Następnie: pozostałe przepływy użytkownika i bramki wydania z rejestru F01–F25.
Równolegle domknąć dowody operacyjne A04: doręczenie alarmu aplikacji nr 22,
zewnętrzny test wykrycia awarii i aktualność kopii produkcji. Wdrożenie 2.19.8,
próby awarii w izolacji i syntetyczny restore zgodnej wersji są już sprawdzone.
[Odbiór monitoringu](odbior-monitoringu-2026-10-02.md) oraz
[próby awarii i odtwarzania](odbior-a04-awarie-2026-10-02.md).
Harmonogramy retencji, rezerwacji i A04 zostały potwierdzone w logach 1.10;
nie trzeba ponownie prosić właściciela o ich pierwszy odczyt.
[Protokół operacyjny](odbior-operacyjny-2026-10-01.md) rozdziela wdrożenie,
zerowe przebiegi i scenariusze, których jeszcze nie odebrano.
Nie utożsamiamy zielonych testów kodu z ukończonym odbiorem komercyjnym.

Końcowe odbiory operacyjne i wydajność pozostają osobnymi bramkami wydania.
Poniższy rejestr F01-F25 zachowuje dotychczasowy zakres i historię.

Data rozpoczęcia: 9.09.2026. **Ostatni przegląd: 2.10.2026.**
Bieżący stan ustaleń jest w rejestrze A01–A05 powyżej i F01–F25 niżej.
Opisy historycznych etapów nie zastępują tych statusów. Akapit niżej zostaje jako
zapis z 13.09.2026 i od tamtego dnia się nie zmienia.

Numeru wersji tu nie ma świadomie. Stał tutaj do 30.09.2026 i zdążył się
rozjechać o trzy wydania przez jeden dzień pracy - pole, które starzeje się
przy każdym wydaniu, będzie się starzeć dalej, niezależnie od dobrych intencji.
Co jest na produkcji, mówi `/health/`; co jest w repozytorium,
`chatbot_project/wersja.py`. Oba są zawsze aktualne, bo nie da się ich zapomnieć.

**Zapis z 13.09.2026. Backend scalony i wdrożony do #62 włącznie: #56 (F25, 2.0.15), #57 (F17, 2.0.16), #58 i #59 (F10, 2.0.17-2.0.18), #60 (F19, 2.0.19), #61 (pomiar wariantów promptu, 2.0.20) i #62 (poprawka promptu F25, 2.0.21); panel frontend_chatbot#16. Etap 5 zamknięty poza F18. Pełna kopia i próba odtworzenia (2.0.14) nadal czekają na odbiór operacyjny, więc F18 nie włącza automatycznego usuwania. 14.09.2026: etap 6 zamknięty - F11 #64, #65 i #66 (2.0.22-2.2.0) oraz panel #17 i #18 scalone, odbiór w trybie testowym Stripe zaliczony. Następny: etap 7, zaczynamy od F16 (część 1: 2.3.0).**

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
| 2. Prywatność i ochrona danych | F04, F05, F12, F13 | Prywatny storage dokumentów/kopii, podpisane odczyty i szyfrowanie; bezpieczna retencja, Docker i zależności | PR #39–#41 scalone; prywatny storage i niezależny klucz kopii sprawdzone. PITR instancji dostępny. Kopia i odtworzenie odebrane 17.09.2026 ([protokół](odbior-f21.md#wynik-odbioru---17092026)): pełna kopia produkcji z plikami, restore na PG16, monitor braku przebiegów i sprawdzony alarm. Nadal: końcowe skany wszystkich repozytoriów |
| 3. Bezpieczne wejścia i koszty | F06, F08, F09, F23 | SSRF, upload, rezerwacje wiadomości, odporne formularze | Backend #42–#44 oraz frontend #11 scalone. Backend web live na `e5259ce` (F08). Strona marketingowa #1 live na `43a36d0`; rzeczywista wiadomość przeszła kolejkę i SMTP, właściciel potwierdził odbiór. Nadal: odbiór uploadu, kontrola rezerwacji/alertów i końcowy odbiór F23 opisany niżej |
| 4. Konta i sesje | F07, F14, F15; reset hasła z F22 | Walidacja kont, MFA, cookies/CSRF, reset i własne sesje | #48–#54 i panel #15 wdrożone; backend 2.0.13, powiadomienia zapisują się do trwałej kolejki. Nadal: rzeczywisty odbiór ustawień i poczty, retencja, alarmy i procedura utraty MFA |
| 5. Wiedza i cykl życia danych | F10, F17, F18, F19, F25 | Kompletny import, atomowa publikacja embeddingów i usuwanie pochodnych, poprawne CSV i feedback, wyszukiwanie FAQ i regresja RAG | F25: #56, #61, #62 scalone i odebrane pomiarem (2.0.21). F17: #57 (2.0.16). F10: #58, #59 (2.0.17-2.0.18). F19: #60 (2.0.19). F18: część 1 (2.8.1) - spójne usuwanie plików, bez nowego automatycznego usuwania; reszta po odbiorze pełnego odtworzenia |
| 6. Płatności | F11; status płatności z F22 | Idempotencja Checkout/webhooków, identyfikatory i okresy Stripe, retry/uzgadnianie; UI potwierdza konkretny zakup | Zamknięty 14.09.2026: #64 (2.0.22), #65 (2.1.0), #66 (2.2.0), panel #17 i #18 scalone; odbiór części 1 i 2 w trybie testowym Stripe zaliczony, uwagi z odbioru naprawione w 2.2.0. Po wdrożeniu produkcyjnym: pierwszy prawdziwy zakup obserwowany w logach |
| 7. Wydajność i obsługa | F16, F20, F21, F24; pozostałe F22 | Paginacja/N+1, SLO, dziennik i minimalizacja danych, alarmy/kopie/restore, obowiązkowe bramki CI, pełne stany UI | F16 część 1 scalona (#67, panel #19, 2.3.0): stała liczba zapytań na listach panelu, Konwersacje i Zapytania stronami, filtr ocen ograniczony do firmy. Część 2 scalona (#68, panel #20, 2.4.0): dokumenty i FAQ stronami, limit publicznego FAQ, eksport CSV strumieniem. Część 3 scalona (#69, 2.4.1): jedno uwierzytelnienie na żądanie, limit panelu oddzielony od limitu czatu, wolne żądania w logu, propozycja SLO - F16 zamknięte w kodzie. F24 scalone (#70, #71, panel #21): blokujące bramki CI, ochrona `main`, mypy 0. F20 część 1 scalona (#72, panel #22, 2.5.0): eksporty i pobrania oraz logowania w dzienniku z osobą i firmą, Sentry bez tokenów i zapytań z adresu, [przepływy danych i retencja](przeplywy-danych.md) bez nowego usuwania. F22 część 1 scalona (panel #23): formularze Prywatność i Widget nie zapisują niewczytanych ustawień, uczciwe stany ładowania i błędów. F22 część 2 scalona (#73, panel #24, 2.6.0): pierwsze kroki na pulpicie liczone z danych firmy. F22 części 3 i 4 scalone (panel #28, #29): granice ról jako wyjaśnienie zamiast awarii, zmiana roli w Zespole. Przy okazji odbioru roli podglądu wyszły trzy gotowe końcówki bez drogi z panelu - eksport rozmów i pobranie pliku dokumentu (#75, panel #26, 2.7.0) oraz usuwanie dokumentu razem z plikiem z magazynu (#76, panel #27, 2.8.0). F21 zamknięte 17.09.2026 (kopia, odtworzenie, alarmy) - to odblokowuje retencję z F20, która na ten odbiór czekała. Dalej: odbiory F22, okresy przechowywania do decyzji właściciela i etap 8 |
| 8. Odbiór komercyjny | Wszystkie | Staging zgodny z produkcją, negatywne testy dostępu, przegląd infrastruktury, obciążenie, odtworzenie kopii, płatności testowe, onboarding i dostępność | Negatywny test dostępu scalony (#74, 2.6.1): [kontrakt dostępu](kontrakt-dostepu.md) dla każdej trasy i metody API, test zatrzymuje nową końcówkę bez polityki; naprawione: czat panelu dla roli viewer (płatny limit), korzeń API z listą końcówek na sam klucz widgetu, fragmenty obcego dokumentu bez 404. Kontrakt zadziałał przy pierwszej nowej trasie: usuwanie dokumentu (2.8.0) nie przeszło, dopóki nie dostało polityki. Dostępność: powiązane etykiety pól ukrytych za przełącznikami widgetu (panel #25) - test etykiet mierzył tylko pola widoczne w stanie z atrapy. Płatności testowe odebrane w F11. [Plan testu obciążeniowego](test-obciazeniowy.md) przygotowany: narzędzie, warianty środowiska, scenariusze z udziałami, profil dopasowany do limitów planu, koszt tokenów i przewidywane wąskie gardło (wyszukiwanie wektorowe bez indeksu). Odtworzenie kopii odebrane 17.09.2026 ([protokół](odbior-f21.md#wynik-odbioru---17092026)). Czekają na decyzje właściciela: staging, narzędzie i środowisko testu obciążeniowego wraz z kosztem rozmów, odbiór pierwszych kroków i dostępności |

## Historia przygotowania — pełna kopia i odtwarzanie, 2.0.14

- Dane SaaS i bajty dokumentów/logo/awatarów, snapshot REPEATABLE READ,
  szyfrowanie w częściach i uwierzytelniony manifest. Kopia wymaga faktycznego
  wstrzymania zapisów; flaga operatora sama nie zatrzymuje usług.
- Zabezpieczona próba dopuszcza tylko pustą lokalną bazę, zgodny schemat,
  wersję PostgreSQL/aplikacji i klucz Django. Weryfikuje rekordy i komplet
  powiązań plików; nie uruchamia workera ani serwera.
- Lokalnie 93 testy nowych/starych kopii, odtwarzania i health przeszły;
  45 nowych przypadków. Bandit nowych modułów: 0, mypy: 218 wcześniejszych
  błędów bez wzrostu. Pełny wynik CI zapisujemy w opisie PR-a.
- Brak migracji, nowych usług, kluczy i zmian panelu. Starsze kopie nadal działają.
- Źródło SaaS: #54 live na web i workerze `ac7c51f`. W tym etapie nie
  zatrzymywano produkcji ani nie kopiowano/odtwarzano rzeczywistych danych.

[Instrukcja, limity, izolacja i odbiór](pelna-kopia-i-odtworzenie.md).
F04/F21 pozostają otwarte do produkcyjnej kopii, izolowanego odtworzenia PG16,
pomiaru RPO/RTO i potwierdzenia harmonogramu oraz alarmów. Przed tym odbiorem
nie włączamy nowych operacji automatycznego usuwania danych.

## Etap 2.0.13 — historia przygotowania (obecnie #54 wdrożony)

- Transakcyjny outbox dla zmiany w ustawieniach i resetu; obecny worker/beat,
  pięć prób łącznie, odzyskanie po przerwaniu i ograniczona wielkość partii.
- Migracja 0037 dodaje tabelę. Bez nowego panelu, usług, sekretów i retencji.
- Kontrola `check_password_notifications` wykrywa zaległe/nieudane wiadomości;
  skonfigurowanie odbiorcy alarmów pozostaje otwarte.
- Odczyt Rendera 12.09 potwierdził jeden worker z beat, obecność SMTP i zgodny
  adres panelu. Obie usługi nadal na 2.0.12. Nie zmieniano produkcji ani nie
  wysyłano rzeczywistych wiadomości w ramach tego etapu.
- Testy i końcowy CI: opis PR-a. [Wdrożenie, ograniczenia i rollback](powiadomienia-o-zmianie-hasla.md).

Kolejność po tym PR-ze: odebrać konta/pocztę → pełny restore bazy i plików →
retencja, alarmy i utrata MFA → dokumenty/RAG → płatności → wydajność/UX/CI →
odbiór komercyjny. Pełny restore poprzedza produkcyjne włączenie nowych operacji
automatycznego usuwania. Rejestr F01–F25 poniżej zachowuje cały zakres audytu.

## Najbliższa kolejność prac

Stan 2.10.2026. [Protokół operacyjny](odbior-operacyjny-2026-10-01.md)
potwierdza raport plików, migracje, nocne przebiegi i brak bieżących zaległości.
Wcześniejsze opisy etapów zachowują historię, ale poniższa kolejność jest aktualna.

**Bieżąca blokada bezpieczeństwa z CI 2.10:** pypdf 6.16.2 ma osiem zgłoszonych
podatności. Przygotowano 2.19.9 z pypdf 6.19.0; po zielonym CI scalić,
przebudować i potwierdzić wdrożenie web/workera. Bez migracji.
[Szczegóły](odbior-a04-awarie-2026-10-02.md#6-poprawka-bezpieczeństwa-wykryta-przy-odbiorze-ci).

**Wdrożone i potwierdzone:** poprawka PyJWT 2.19.6, jawni odbiorcy alarmów
2.19.7 oraz nadzór Beat/workera 2.19.8. Nie planujemy ponownie ich wdrożenia.
2.10 zaliczono [izolowane próby awarii i odtworzenia](odbior-a04-awarie-2026-10-02.md).

1. **Pozostałe dowody A04 (równolegle).** Potwierdzić doręczenie alarmu aplikacji
   nr 22 obu skrzynkom. Przeprowadzić wykrycie rzeczywistej zmiany health na celu
   testowym przez UptimeRobot oraz osobną próbę zatrzymania Beat. Sprawdzić
   aktualność zgodnej kopii produkcji; syntetyczny restore z 2.10 nie mierzy jej RTO.
   Próby plików R2, awarii procesów i magazynu, lokalnego workera/Redis oraz
   kwarantanny odtworzonych zleceń są zaliczone w opisanym zakresie.
2. **Płatności A01/A02.** Kontrolowany Stripe test mode: podwójny zakup,
   utracona odpowiedź, kolejność zdarzeń, odnowienie/zmiana planu i alarm.
   Automatyczne uzgodnienie działa, lecz aktualnie nie ma powiązanych firm,
   na których można byłoby potwierdzić jego skuteczność.
3. **Rozmowy A03/A05.** Panel i widget: 410/error w SSE, usunięcie w trakcie
   odpowiedzi, nowa rozmowa po usunięciu, retencja 0/3650 i odmowa złych wartości.
4. **Konta i obsługa użytkownika.** Aktywacja i zaproszenia (F07), pełny upload
   i import (F06/F09/F10/F17), ustawienia, MFA i poczta (F14/F15), CSV/oceny
   (F19), pierwsze kroki i stan zakupu (F22), prawdziwy token Turnstile (F23).
   Produkcyjny web ma TRUSTED_PROXY_DEPTH=2; pozostaje test rzeczywistego IP
   i odporności na nagłówek klienta. Nie uznawać odczytu ustawienia za ten test.
5. **Poprawki zaproszeń.** Usunąć niespójny wybór wielu użyć w panelu;
   rozstrzygnąć i sprawdzić potwierdzenie tożsamości adresata. Stan backendu
   opisuje [kontrakt](rejestracja-i-zaproszenia.md).
6. **Bramki wydania.** Macierz dostępu (F01), ponowne skany wszystkich repo
   i faktycznego środowiska produkcyjnego (F05/F12), dostępność,
   test obciążenia i pomiar SLO (F16), ocena potrzeby indeksu wektorowego
   na podstawie pomiaru, RTO odbudowy usług (F21).
7. **Decyzje właściciela.** Cele SLO/SLA, zakres i budżet testu obciążenia
   oraz środowisko testowe. Kopia miesięczna ręczna i obecne zasoby pozostają
   przyjętym wariantem; płatny cron nie jest obowiązkową nową decyzją.
   [Wzór umowy powierzenia](umowa-powierzenia.md) nadal wymaga przeglądu prawnego
   i uzupełnienia decyzji wskazanych w dokumencie, w tym podstaw przekazywania
   danych poza EOG. Ustalić także sposób komunikowania awarii.

**Wykonane w tym kroku:** potwierdzenie przebiegów F08 (04:00),
F13 (03:30), F20 (03:45), A04 (co minutę), A02 (co 5 minut) i kolejki F15;
diagnostyka bieżąca bez zaległości. Nie wysyłano testowych wiadomości,
nie wykonywano płatności ani testowego kasowania w produkcji.

P1 dotyczące kont, administracji i płatności oraz nieodebrane scenariusze
A01–A05 nadal blokują deklarację gotowości komercyjnej.

## Rejestr wszystkich ustaleń

Przegląd 29.09.2026: z kolumny „co pozostaje" zdjęte punkty, które były już
wykonane, a wiersz wciąż ich żądał - wdrożenia #57, #58, #59 i #60 (zapisane
w nagłówku tego pliku jako wykonane 13.09.2026), zajętość bazy wiedzy w panelu,
usuwanie osoby z zespołu, import CSV w panelu oraz retencja i alerty zgłoszeń.
Rejestr, który prosi o zrobioną pracę, przestaje być podstawą decyzji
o kolejności - i przez dwa tygodnie nią nie był.

Przegląd 29.09.2026, drugie podejście: zdjęte „Przegląd i CI" z F10, F16 i F24 -
cały ten kod jest na `main`, co widać po `documents/file_limits.py`,
`WOLNE_ZADANIE_MS` w ustawieniach i po tym, że mypy zgłasza zero błędów.
F10 prosił dodatkowo o wdrożenie web i workera, choć nota poniżej twierdziła,
że takie prośby już zdjęto ze wszystkich czterech wierszy. Zdjęto z trzech.

Dwa punkty przeżyły jeszcze pierwsze podejście do tego przeglądu,
bo sprawdzałem je w niewłaściwym miejscu: importu szukałem po słowie „import"
w panelu, a wywołanie nazywa się `/chat/import/`; retencji zgłoszeń szukałem
w `accounts/retencja.py`, a zgłoszenia znikają razem z rozmowami przez
`chat/retention.py`. **Retencja stoi w tym systemie na dwóch modułach**: stałe
okresy dla danych konta w `accounts/retencja.py` i okres ustawiany przez firmę
dla danych rozmów w `chat/retention.py`. Sprawdzenie jednego z nich nie jest
sprawdzeniem retencji.

| ID | Stan i dowód | Co pozostaje do odbioru lub naprawy |
|---|---|---|
| F01 | Naprawa scalona i wdrożona, backend #38 | Końcowa macierz dostępu przy odbiorze komercyjnym |
| F02 | Naprawa ról i ostatniego właściciela, #38 | Atomowe przyjmowanie zaproszeń należy do F07 |
| F03 | Izolacja CSV naprawiona, #38 | Integralność treści CSV pozostaje w F19 |
| F04 | Prywatne magazyny, szyfrowanie i klucze poza hostingiem; 2.0.14 dodaje pełne kopie z bajtami plików i zweryfikowaną próbę na danych syntetycznych | Wykonane 17.09.2026 razem z F21: rzeczywista kopia przy wstrzymanych zapisach, izolowany restore na PG16, monitor i sprawdzony alarm ([protokół](odbior-f21.md#wynik-odbioru---17092026)). Retencja archiwum kopii dodana w 2.15.0 ([opis](harmonogram-i-kontrola-kopii.md#retencja-archiwum-kopii-2150)) |
| F05 | Bezpieczny kontekst/obraz, #39 | Skan podatności obrazu dodany do CI w 2.18.0 (Trivy, `CRITICAL,HIGH`, tylko podatności z dostępną poprawką, blokujący). Pierwszy przebieg wykrył cztery HIGH w narzędziach budowania - naprawione usunięciem pip, setuptools i wheel z obrazu produkcyjnego, bo podbicie wersji ich nie usuwało. Zostaje skan obrazu faktycznie stojącego na produkcji - CI sprawdza ten zbudowany z bieżącego commita |
| F06 | SSRF, DNS i limity crawlera naprawione, #42 | Odbiór integracji w pełnym przepływie importu |
| F07 | Backend #46/#47 i panel #12 scalone; ich kod zawarty we wdrożonych #52 i panelu #14 | Rzeczywisty odbiór SMTP aktywacji; wartość `TRUSTED_PROXY_DEPTH=2` na web odczytana 1.10.2026; pozostaje odbiór rzeczywistego IP i odporności na podrobiony nagłówek przez `/api/diagnostyka/adres/`; ocena nadużyć przez wiele skrzynek i aliasów **zrobiona w 2.17.0** (zgłoszenie, nie blokada - [opis](rejestracja-i-zaproszenia.md#powtórny-okres-próbny-na-tę-samą-skrzynkę-2170)). Retencja i alerty zgłoszeń **są zrobione**: zgłoszenia znikają razem z rozmowami, po `data_retention_days` firmy (`chat/retention.py`, codziennie 3:30), a o nowym zgłoszeniu powiadamia `powiadom_o_zapytaniu_task` |
| F08 | Rezerwacje i rozliczenie SSE, #44; web live `e5259ce` | Pomiar kosztów zrobiony 28.09.2026 ([koszt klienta](koszt-klienta.md)). Alarm o biletach do rozliczenia i sprzątanie rozliczonych w 2.16.0: komenda istniała od #44, ale nie było jej w harmonogramie, więc nie wykonała się ani razu ([opis](rezerwacje-wiadomosci.md#kto-to-wszystko-uruchamia-2160)). Wynik zadania widać od 2.19.0 w zakładce Stan (karta „Rozliczanie pracy bota”), bez schodzenia do logu usługi ([opis](rezerwacje-wiadomosci.md#kto-to-wszystko-uruchamia-2160)). Potwierdzone 1.10.2026: automatyczny przebieg 04:00 zakończony sukcesem, nierozliczone=0 i usunięte=0; odczyt bieżący także bez zaległości. [Protokół](odbior-operacyjny-2026-10-01.md). Nie wywoływano alarmu z niezerową kolejką |
| F09 | Backend #43 i panel #11 scalone | Produkcyjny odbiór uploadu na wydzielonej firmie |
| F10 | Część 1: #58 scalony (2.0.17): typ treści przy pobieraniu stron, PDF/DOCX/TXT/MD podlinkowane na stronie przez izolowany parser, adres źródła zawsze pobierany, mapy stron stałych przed wpisami, jedna za duża odpowiedź nie przerywa pobierania. Część 2: #59 scalony (2.0.18): limit bazy wiedzy pod blokadą doradczą, zlecenia zadań po zatwierdzeniu transakcji, TXT w Windows-1250, ISO-8859-2 i UTF-16, tabele i pola tekstowe DOCX, przywrócone podłączenie sygnału dokumentów (usunięte w #21, 4.09.2026: dokumenty z panelu bez embeddingów) | Jednorazowe przeliczenie dokumentów bez fragmentów i kontrole z [kompletny-import.md](kompletny-import.md). Część 2 jest na `main` i wdrożona - `documents/file_limits.py`, `zablokuj_baze_wiedzy` w walidatorach i `on_commit` w sygnałach (sprawdzone 29.09.2026) |
| F11 | Część 1: #64 wdrożony (2.0.22), migracja 0038 na produkcji; stan subskrypcji pobierany ze Stripe, dostęp do końca opłaconego okresu + 3 dni przy nieudanym odnowieniu, blokada drugiego zakupu, klucz idempotencji. Odbiór w trybie testowym 14.09.2026: zakup, odmowa drugiego zakupu, powtórka zakupu po anulowaniu i nieudane odnowienie zaliczone ([wynik](platnosci-spojnosc.md#wynik-odbioru---14092026)). Część 2 przygotowana do przeglądu (2.1.0): portal Stripe do zmiany planu (wyższy od razu z dopłatą, niższy od następnego okresu), karty, faktur i anulowania; potwierdzenie konkretnej sesji Checkout z uzgodnieniem stanu; zakup i portal tylko dla właściciela; e-mail przy wejściu w `past_due` | Część 2 scalona (#65, frontend_chatbot#17), odbiór w trybie testowym 14.09.2026: zakup bez webhooka, podwyżka z dopłatą, obniżka od następnego okresu, portal, uprawnienia, zmyślona sesja i nieudana płatność zaliczone ([wynik](platnosci-portal.md#wynik-odbioru---14092026)). Uwagi z odbioru (anulowanie i zaplanowana obniżka niewidoczne w panelu, anulowany plan jako obecny, 429 na ekranie płatności) naprawia 2.2.0 - przegląd, CI, migracja 0039 i wdrożenie. Po wdrożeniu produkcyjnym: pierwszy prawdziwy zakup obserwowany w logach |
| F12 | DRF i strona poprawione; panel #13 aktualizuje Next.js do 16.3.5, sharp do 0.35.4 i zależności pośrednie; npm audit: 4 zgłoszenia → 0 | Panel #13: CI zielone, produkcja wdrożona. Skany powtórzone 30.09.2026 i obie strony wymagały poprawki: PyJWT 2.13.0 miał 10 CVE (→ 2.14.0, #107), a `npm audit` dwa zgłoszenia o wysokiej wadze w zależnościach pośrednich - `undici` z obejściem weryfikacji certyfikatu TLS i wyciekiem cudzych ciasteczek oraz `brace-expansion` (→ 0, panel #34). Obie bramki zatrzymały PR-y, których te podatności nie dotyczyły, i o to w nich chodzi. Skan przed samym wydaniem trzeba i tak powtórzyć - lista zmienia się co tydzień |
| F13 | Retencja aktywnych rozmów naprawiona, #39 | Polityka wdrożona w 2.11.0, okresy zatwierdzone przez właściciela 17.09.2026. Przebieg z harmonogramu potwierdzony 1.10.2026 o 03:30: sukces, wynik {} (brak raportowanych usunięć). Kontrola istniejących okresów prawidłowa. [Protokół](odbior-operacyjny-2026-10-01.md); pełny odbiór A03/A05 pozostaje osobny |
| F14 | #48/#52/#53 wdrożone: MFA, aktualne hasło przy konfiguracji, kod przy zmianie hasła i kończeniu sesji | Odbiór nowych ustawień i procedura utraty MFA. Retencja wyzwań MFA objęta F20 (2.11.0): 24 h po wygaśnięciu |
| F15 | #49–#54 i panel #15 wdrożone; reset, sesje i trwałe powiadomienia po zmianie hasła. CI #54: 1791 testów, 88,21% | Rzeczywisty odbiór ustawień i poczty. Retencja sesji i kolejki powiadomień objęta F20 (2.11.0). Alarmy: czujka z zewnątrz ustawiona 28.09.2026, alarm wywołany próbnie i odebrany ([opis](monitoring-dostepnosci.md)) |
| F16 | Część 1 scalona (#67, panel #19, 2.3.0): pomiar liczby zapytań na wszystkich listach panelu (3 i 30 obiektów) wykrył N+1 w dokumentach (2 zapytania na dokument) i historii rozmów (1 na wpis) - naprawione, test pilnuje stałej liczby zapytań; historia rozmów i zapytania kontaktowe stronami (50, maks. 200); filtr ocen w historii ograniczony do rozmów firmy. Część 2 scalona (#68, panel #20, 2.4.0): dokumenty i FAQ stronami od najnowszych, publiczne FAQ widgetu najwyżej 100 wpisów, eksport CSV (API i panel administracyjny) strumieniem. [Opis](listy-i-zapytania.md). Część 3 przygotowana do przeglądu (2.4.1): jedno uwierzytelnienie na żądanie (żądanie panelu z JWT: 7 → 4 zapytania na /api/accounts/me/), limit panelu oddzielony od limitu czatu z testem pilnującym widoków widgetu, wolne żądania w logu (`WOLNE_ZADANIE_MS`), propozycja SLO. [Opis](slo-i-czasy-odpowiedzi.md) | Akceptacja celów SLO przez właściciela i tydzień pomiaru wyjściowego; test obciążeniowy w odbiorze komercyjnym (etap 8). Część 3 jest na `main` - `WOLNE_ZADANIE_MS` w `chatbot_project/settings/base.py` (sprawdzone 29.09.2026) |
| F17 | #57 scalony (2.0.16): publikacja w jednej transakcji pod blokadą wiersza dokumentu, kontrola aktualności treści, pominięcie dokumentów bez zmian, `acks_late` zadania i status błędu przy dokumencie | Kontrole z [atomowa-publikacja-wektorow.md](atomowa-publikacja-wektorow.md) |
| F18 | Część 1 (2.8.1): plik znika z magazynu razem z wierszem, do którego należał - każdą drogą usunięcia, nie tylko przyciskiem w panelu (panel administracyjny, kaskada przy usunięciu firmy, `queryset.delete()`); wymiana logo albo awatara kasuje poprzedni obraz. Kasowanie po zatwierdzeniu transakcji, z wyjściem przy odtwarzaniu kopii. [Opis](usuwanie-plikow.md) ; część 2 (2.11.1): limit blokuje wzrost bazy, a nie stan „ponad limit" - po zejściu z wyższego planu klient może odświeżać i zmniejszać wiedzę, czego wcześniej nie mógł, a komunikat rozróżnia „przekroczyłaby" od „przekracza" | **Zamknięte 29.09.2026.** Raport plików osieroconych okazał się zbędny (17.09.2026: 1 obiekt w magazynie wobec 1 dokumentu z plikiem, zero sierot). Zajętość bazy wiedzy widać w panelu na liście dokumentów (2.12.0 i panel #32): pasek z procentem, także powyżej 100%, więc klient nie dowiaduje się o przekroczeniu dopiero przy nieudanym wgraniu |
| F19 | #60 scalony, produkcja zwraca 2.0.19: neutralizacja formuł i BOM w obu eksportach, eksport odporny na rozmowy usunięte retencją, import w całości albo wcale z limitami i czytelnymi błędami, import poza statystykami ruchu, ocena z widgetu wymaga sesji rozmowy, panel ocenia tylko rozmowy testowe | Kontrole z [csv-i-oceny.md](csv-i-oceny.md) |
| F20 | Częściowo: 2.0.11 ogranicza body/cookies/zmienne lokalne i argumenty zadań w Sentry; 2.5.0 (część 1): odczyty wynoszące dane i zdarzenia dostępu w dzienniku z osobą i firmą, Sentry bez zapytań i tokenów z adresu, log bez e-maila zaproszenia, inwentarz przepływów i retencji ; 2.10.0: `raport_retencji` - ile danych zniknęłoby przy każdym progu, z liczbami zgodnymi z tym, co zrobi usuwanie; nic nie kasuje ; 2.11.0: okresy zatwierdzone przez właściciela 17.09.2026 (dziennik 12 mies., zaproszenia 30 dni, sesje i wyzwania MFA 24 h po wygaśnięciu, rejestracje 7 dni, powiadomienia 90 dni), reguły w jednym module dla raportu i usuwania, nocne zadanie o 3:45 na istniejącym workerze, testy granic i przebiegu przerwanego w połowie | Retencja Rendera (7 dni) i Sentry (30 dni, plan Developer) sprawdzone 28.09.2026 i wpisane do tabeli przepływów. Historyczny brak rejestracji zadania naprawiony w 2.14.1. Przebieg z harmonogramu potwierdzony 1.10.2026 o 03:45: sukces, wszystkie sześć liczników = 0. [Protokół](odbior-operacyjny-2026-10-01.md). Zerowy przebieg nie jest próbą kasowania ani pełnym odbiorem polityki danych |
| F21 | Kontrola kopii #41, dostępny PITR; 2.0.14: zaszyfrowany pełny format, próba odtworzenia bazy i plików na danych syntetycznych; 2.9.0: `kontrola_pelnej_kopii` (sama znajduje najnowszą kopię `.saas`, brak kopii to błąd, nie cisza), `kontrola_obecnosci_kopii` (bez klucza szyfrowania, do uruchomienia poza Renderem) i przebieg GitHub Actions jako niezależny monitor braku przebiegów; [protokół odbioru](odbior-f21.md). **Zamknięte 17.09.2026.** Pierwsza pełna kopia produkcji, izolowane odtworzenie na PG16 w 2,49 s, dane i pliki w komplecie, RTO danych ~10 min. Kopia miesięczna ręcznie (decyzja właściciela: bez płatnego crona), deklarowane RPO do miesiąca. Monitor braku przebiegów co tydzień poza Renderem, alarm wywołany próbnie i odebrany - pierwsza próba wykryła, że przebieg połyka kod błędu w potoku (2.9.2). [Wynik](odbior-f21.md#wynik-odbioru---17092026) | RTO produkcji niezmierzone (wymaga odbudowy usług). Retencja archiwum dodana w 2.15.0: 365 dni dla pełnych kopii, 90 dla dziennych, zawsze zostają 3 najnowsze; uruchamiana ręcznie, bo kopie też powstają ręcznie ([opis](harmonogram-i-kontrola-kopii.md#retencja-archiwum-kopii-2150)) |
| F22 | Upload, formularze, reset i ustawienia bezpieczeństwa wdrożone w panelu #15/backendzie #53. Stan zakupu w F11 część 2 (2.1.0): strona sukcesu pyta o konkretną sesję, rozróżnia aktywny plan, płatność w toku, wygasłą sesję i cudzą albo nieistniejącą płatność; ostrzeżenie o nieudanej płatności na ekranie Subskrypcja. Część 1 (panel #23): Prywatność i Widget blokują zapis do poprawnego odczytu ustawień (wcześniej zapis wartości domyślnych mógł skrócić okres przechowywania i usunąć rozmowy), Zespół i Subskrypcja bez fałszywych pustych stanów. Część 2 (2.6.0): lista pierwszych kroków na pulpicie - wiedza, rozmowa testowa, widget na publicznej witrynie, adres powiadomień, polityka prywatności. Część 3 (panel #28): granica roli pokazywana jako wyjaśnienie, nie awaria - Zespół i Ustawienia konta zamiast komunikatu z DRF, pracownik bez formularza zaproszeń, który i tak go odbijał. Część 4 (panel #29): zmiana roli osoby w Zespole, dotąd możliwa wyłącznie przez API albo panel administracyjny; odmowa backendu cofa wybór i pokazuje powód (ostatni aktywny właściciel) | Odbiór ustawień i rzeczywistych e-maili; odbiór stanu zakupu z F11; odbiór listy pierwszych kroków na nowym koncie. Import CSV **jest** w panelu od 16.09.2026 (frontend_chatbot#31, Konwersacje: pole pliku, potwierdzenie przed wgraniem, wynik i granica roli), usunięcie osoby z zespołu też - oba wiersz żądał jeszcze po wdrożeniu |
| F23 | Kod #1 strony wdrożony; test SMTP i odbiór w skrzynce zaliczone | Pełny E2E Turnstile, rzeczywiste IP za proxy, alerty. Docelowy proces backup/restore zamknięty w F21 17.09.2026 ([wynik](odbior-f21.md#wynik-odbioru---17092026)) |
| F24 | Część 1 scalona (#70, panel #21): wszystkie kontrole CI backendu blokujące, eslint bez ostrzeżeń, test martwych odnośników w dokumentacji, README bez nieaktualnych ograniczeń; ochrona `main` w obu repozytoriach ustawiona przez właściciela 15.09.2026 (wymagane kontrole CI, obejście dla administratora). Część 2 przygotowana do przeglądu: mypy 47 → 0 (puste listy uprawnień jako krotki, adnotacje w panelu administracyjnym, wyjątki Stripe, typy parametrów), ruff 29 → 15 (długie wiersze w kodzie złamane, treść szablonu e-maila i fixtur z wyjątkiem) | **Zamknięte 29.09.2026.** Część 2 jest na `main`: mypy zgłasza 0 błędów, ruff dokładnie 15 - czyli te, które wiersz opisuje jako zostawione świadomie (9 pól tekstowych z null=True, bo migracja szłaby po żywej bazie, i 6 uwag o kolejności w modelach) |
| F25 | #56 scalony (2.0.15): FAQ wybierane po dopasowaniu do pytania, treść klienta między ogranicznikami, wycięcie tokenów protokołu z treści; regresja RAG już w CI | Zamknięte 13.09.2026. Regresja znacznika z 2.0.15 wykryta przy odbiorze, przyczyna wskazana pomiarem wariantów (#61), poprawka #62. Odbiór 2.0.21 na produkcji, 5 powtórzeń: odmowy trafne 100%, fałszywe 0%, uprzejmości 0% i 0%, oparte na wiedzy 100%. Szczegóły w [faq-i-rozdzielenie-tresci.md](faq-i-rozdzielenie-tresci.md) |

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
F20 część 1 (2.5.0) uzupełnia dziennik o eksporty, pobrania plików i zdarzenia
dostępu przypisane do osoby; otwarta pozostaje retencja wpisów, patrz
[przepływy danych](przeplywy-danych.md).

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
