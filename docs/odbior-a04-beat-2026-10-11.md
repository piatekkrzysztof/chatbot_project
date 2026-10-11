# Odbiór A04 - zatrzymanie Beat i workera, 11.10.2026

Ostatnia próba z [nadzoru Beat i workera](monitoring-workera.md#wdrożenie-i-odbiór-krok-po-kroku)
(kroki 4 i 5). Protokół zabrania jej na produkcji, więc - zgodnie z decyzją
właściciela z 11.10.2026 - wykonana w izolowanym środowisku lokalnym.

## Środowisko

- Kod: main z 2.31.1. Osobna baza `a04_20261011` (PostgreSQL 15), osobny
  Redis (kontener, port 56380), web `runserver` na porcie 8001, worker
  (`-P solo`) i **osobny demon Beat** pracujący według zwykłego harmonogramu
  (próba monitora co minutę). Maile wyłącznie na konsolę. Produkcji nie dotykano.
- Rejestrator co 5 s czytał `/health/` przez HTTP i wiek ostatniej publikacji
  z tabeli `accounts_przebiegmonitora`. Pełny zapis:
  [odbior-a04-beat-2026-10-11.jsonl](odbior-a04-beat-2026-10-11.jsonl) (UTC).

## Przebieg (czas lokalny, CEST)

| Czas | Zdarzenie | `/health/` |
|---|---|---|
| 19:29:51 | start, pierwsza próba Beat → Redis → worker → baza | HTTP 200, zadania=true, **ok** |
| 19:30:06 | **zatrzymany wyłącznie Beat**; worker, Redis i web działają | - |
| 19:32:48 | wiek publikacji ok. 180 s | HTTP 200, broker=true, zadania=false, **ograniczony** |
| 19:33:05 | Beat wznowiony | - |
| 19:33:17 | świeża próba | HTTP 200, **ok** |
| 19:33:29 | **zatrzymany wyłącznie worker**; Beat dalej publikuje | - |
| 19:36:14 | wiek publikacji ok. 180 s; w kolejce 10 zaległych wiadomości | HTTP 200, broker=true, zadania=false, **ograniczony** |
| 19:36:27 | zatrzymany także Beat; 70 s oczekiwania, aż wszystkie próby w kolejce przekroczą 60 s ważności | - |
| 19:37:46 | worker wznowiony **bez Beat** | - |
| 19:38:12 | worker odbiera 3 zaległe próby monitora i odrzuca je („Discarding revoked task”, wygasłe); kolejka pusta | nadal **ograniczony**, wiek 313 s i rośnie |
| 19:38:42 | Beat wznowiony | - |
| 19:38:51 | świeża próba | HTTP 200, **ok** |

## Wynik

- **Krok 4 - zaliczony.** Samo zatrzymanie Beat jest wykrywane po ok. 180 s:
  HTTP pozostaje 200 (Render nie restartuje weba), broker=true, zadania=false,
  stan ograniczony. Po wznowieniu Beat powrót do ok w 12 s.
- **Krok 5 - zaliczony.** Zatrzymany worker przy działającym Beat jest
  wykrywany tak samo. Zaległe wiadomości po wznowieniu workera **nie odnawiają
  zdrowia** - wygasły i zostały odrzucone; zdrowie wraca dopiero ze świeżą
  próbą.

## Czego ta próba nie obejmuje

- Infrastruktury Rendera (restart procesu przez platformę, proxy).
- **Wykrycia przez monitor zewnętrzny.** UptimeRobot alarmuje o braku frazy
  `"stan": "ok"` - powiadomienia Test Notification doszły 2.10, ale wykrycie
  rzeczywistego braku frazy na celu testowym nie było mierzone. Do zrobienia
  przez właściciela przy zakładaniu strony statusu
  ([informowanie o awariach](informowanie-o-awariach.md)): osobny monitor
  słowa kluczowego z frazą, której na pewno nie ma, odebrany alarm, potem
  poprawna fraza i alarm powrotu.
