# Pojemność HTTP na 512 MiB — 2.23.0

## Problem i wynik

Pomiar na main 0abb579 wykazał, że jeden worker sync zajęty 4-sekundowym SSE
wstrzymuje panel na 3,76 s. Dwa strumienie na dwóch wątkach wstrzymywały panel
na 3,71 s, cztery na czterech — na 3,75 s. Strumień 33-sekundowy na sync
z timeoutem 30 s został zerwany przez WORKER TIMEOUT.

Profil 2.23.0 to **jeden worker gthread, cztery wątki**. W procesie można
prowadzić najwyżej **dwie rozmowy i jeden upload**. Pozostaje nominalnie jeden
wątek na panel, usunięcie rozmowy i szybką odmowę kolejnej ciężkiej operacji.
Nie jest to gwarancja czasu odpowiedzi przy dowolnej liczbie połączeń: również
autoryzacja, baza, sieć i inne widoki mogą oczekiwać na zasoby.

## Jak działa ograniczenie

- Wspólny limit rozmów obejmuje `/api/chat/`, `/api/chat/test/`,
  `/api/widget/chat/` oraz `/api/widget/chat/stream/`. Dotyczy wszystkich firm
  w procesie, niezależnie od istniejącego limitu i rozliczeń konkretnej firmy.
- Wspólny limit uploadów obejmuje dokumenty, import historii CSV i zapis
  brandingu (także logo/avatar). Slot jest zajęty od zakończenia kontroli DRF
  do końca obsługi widoku: przed odczytem request.data, przez parser i zapis.
  Zapis brandingu bez pliku także podlega temu limitowi.
- GET, HEAD, OPTIONS i DELETE nie zajmują tych slotów. Odczyt i usuwanie
  rozmowy testowej nie konkurują z jej generowaniem o slot rozmowy.
- Nie ma czekania na semafor: zajęty limit daje HTTP 503, JSON
  `{"detail":"Serwer obsługuje teraz inne zadania. Spróbuj ponownie za chwilę.",
  "code":"server_busy"}` i `Retry-After: 1`. To wskazówka ponowienia,
  nie gwarancja wolnego miejsca po sekundzie.
- Ograniczenie następuje po autoryzacji, uprawnieniach i throttlingu DRF,
  przed utworzeniem rozmowy, rezerwacją wiadomości lub zapisem danych.
  Odmowa nie pobiera wiadomości z abonamentu; próba nadal podlega zwykłemu
  limitowi częstotliwości żądań.
- Dla SSE slot przechodzi na iterator odpowiedzi. Koniec, wyjątek,
  rozłączenie i close nieodczytanej odpowiedzi zwalniają go dokładnie raz.
  Istniejący ReservedStream nadal odpowiada za rozliczenie wiadomości.
- Semafory są lokalne dla procesu. Nie zwiększać liczby workerów bez
  nowego pomiaru: każdy proces ma własny budżet, własną pamięć i własne sloty.
  To ochrona WSGI; nie jest rozproszonym limitem ani profilem ASGI.

Istniejący parser_slot i limit pamięci parsera pozostają włączone. Limit
uploadu obejmuje także oczekiwanie na zapis magazynu. Nie obejmuje osobnego
workera Celery, operacji administracyjnych ani wszystkich zadań utrzymaniowych.

## Powtórzony odbiór lokalny — 5.10.2026

Produkcji nie zmieniano. Zbudowano produkcyjny etap Dockerfile z kodem zmiany.
Gunicorn uruchomiono z `python:chatbot_project.gunicorn_config`, podmieniając
tylko aplikację WSGI na harness z syntetycznym dostawcą odpowiedzi.
Kontener: 512 MiB, brak dodatkowego swapu, 1 CPU, 128 procesów/wątków.
Pełne Django, prawdziwy HTTP/JWT, PostgreSQL 16.15 i pgvector, 500 fragmentów.
Wywołania OpenAI i zlecenie kolejki zastąpiono atrapami; pliki zapisywano
w prywatnym tmpfs. Cache lokalny, DEBUG=False, OPENBLAS_NUM_THREADS=1.
To nie jest pomiar wydajności rzeczywistego OpenAI, R2 ani Redis/Celery.

| Scenariusz | Bez nacisku pamięci | Punkt wyjścia około 330 MiB |
|---|---:|---:|
| Panel podczas 2 SSE i uploadu PDF | 36 ms / 200 | 36 ms / 200 |
| Nadmiarowe rozmowy (wszystkie 4 trasy) | 32–40 ms / 503 | 27–41 ms / 503 |
| Drugi upload, PDF bliski 10 MiB | 74 ms / 503 | 52 ms / 503 |
| Przyjęty PDF 200 stron | 2,90 s / 201 | 3,06 s / 201 |
| Dwie przyjęte rozmowy | obie `done` | obie `done` |

Maksimum całego kontenera: **364,25 MiB**, z próbkowaniem i procesem sztucznego
nacisku wliczonymi w pamięć. `oom_kill=0`, `memory.failcnt=0`.
Sloty ponownie działały po ukończeniu rozmowy, odmowie pliku 413 i trzech
kolejnych rozłączeniach klientów. Wyniki to pojedyncze scenariusze, nie p95/SLO.

Dowody: [przed zmianą](pomiary-gunicorn-przed-2026-10-05.json),
[po zmianie](pomiary-pojemnosci-http-2026-10-05.json).
Lokalnie 117 testów ograniczenia, czatów, dokumentów, CSV i parsera przeszło;
Ruff, mypy nowych modułów, Bandit nowych modułów oraz budowa obrazu przeszły.
Pełne CI jest osobną bramką PR i jego wynik należy sprawdzić przed scaleniem.

## Wdrożenie ręcznej usługi Render — osobny krok

1. Scalić PR po zielonym CI. Upewnić się, że wdrażany commit zawiera 2.23.0.
2. Odczytać i zapisać bieżący Start Command, WEB_CONCURRENCY i ewentualne
   GUNICORN_CMD_ARGS. Zachować poprzedni commit i komendę do powrotu.
3. Ustawić Start Command:

   ```sh
   gunicorn --config python:chatbot_project.gunicorn_config
   ```

4. WEB_CONCURRENCY ustawić na 1. Profil jawnie ustawia workers=1; usunąć
   kolidujące nadpisania workerów, threads, worker-class i timeout z innych
   argumentów. Nie zmieniać pozostałych zmiennych, sekretów ani usług.
5. Wykonać kontrolowany deploy, sprawdzić wersję health oraz log startu:
   jeden worker gthread. Samo scalenie render.yaml nie konfiguruje ręcznie
   utworzonej usługi. Docker i blueprint już wskazują wspólny profil.
6. Odebrać uzgodnione syntetyczne próby na produkcji: 2 rozmowy + panel,
   nadmiarowa rozmowa 503, upload + drugi upload 503, rozłączenie i usunięcie
   rozmowy podczas SSE. Sprawdzić pamięć, restart workera i rozliczenia.
7. Przy regresji przywrócić zapisaną komendę/commit. Brak nowych migracji.
   Powrót do starego sync przywraca jego znane blokowanie i timeout SSE.

Gunicorn timeout=30 dotyczy żywotności workera, nie maksymalnego czasu
pojedynczego żądania gthread. Graceful timeout=100 daje czas aktywnej rozmowie,
ale hosting może narzucić krótszy termin zabicia procesu. Limity aplikacji
(SSE 90 s, klient OpenAI 60 s) pozostają bez zmian; sprawdzenie deadline jest
wykonywane pomiędzy zdarzeniami dostawcy, a nie przez niezależny zegar.

## Co pozostaje

- Odbiór rzeczywistej konfiguracji Rendera i zachowania panelu/widgetu przy 503.
- Dłuższy test stabilności, reprezentatywne pliki i wolny/awaryjny R2.
- Próby zawieszonego dostawcy, przekroczenia 90 s i restartu długiego SSE,
  z kontrolą naliczeń i czasu narzuconego przez hosting.
- Pozostałe odbiory A01/A02, A03/A05 w przeglądarce i izolowane zatrzymanie Beat.
