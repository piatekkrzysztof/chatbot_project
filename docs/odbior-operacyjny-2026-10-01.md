# Odbiór operacyjny — 1.10.2026

Aktualizacja po późniejszej próbie produkcyjnej: [odbiór A04, naprawa
uprawnień i ograniczenie pamięci workera](odbior-a04-produkcja-2026-10-01.md).
Poniższy raport zachowuje wyniki odczytu z godziny 10:15–10:19; jego
lista otwartych prób opisuje stan przed późniejszym testem.

## Zakres i wynik

Odczyt produkcji 1.10.2026 około 10:15–10:19 CEST (Europe/Warsaw).
Backend zwrócił wersję 2.19.5, commit
`47298bd31c2f7f8a26c5a178591f6d1a06c38fe8`, HTTP 200 oraz dostępność
bazy i brokera. Ten sam commit był potwierdzony jako Live na web i workerze
30.09 podczas odbioru raportu plików.

Odczytano logi istniejącego workera oraz wykonano komendy wyłącznie
diagnostyczne. Nie uruchamiano zadań ręcznie, kasowania, ponowień,
uzgadniania płatności ani wysyłki wiadomości. Nie zmieniano konfiguracji,
danych klientów, wdrożeń ani harmonogramów.

**Potwierdzono działanie harmonogramu. Nie zamyka to odbioru całego SaaS.**
Zerowy wynik zadania jest dowodem jego zakończenia, jeżeli istnieje wpis
`succeeded`; sama pusta baza lub rejestracja nazwy zadania nim nie jest.
Zerowy przebieg nie sprawdza działania na danych wymagających usunięcia
ani dostarczenia alarmu.

## Przebiegi z harmonogramu

Źródło: logi Rendera, celery-worker, zakres ostatnich 24 godzin.
Godziny z 1.10.2026 w Europe/Warsaw (UTC+02:00). Dla zadań poniżej
potwierdzono zlecenie przez Beat, odbiór przez worker i zakończenie
`succeeded`, a nie tylko obecność w spisie zadań.

| Zakres | Zadanie | Zakończenie | Czas | Wynik |
|---|---|---|---|---|
| F13 / A03 / A05 | `chat.tasks.purge_expired_conversations` | 03:30:02,438 | 2,426 s | `{}` — brak raportowanych usunięć |
| F20 | `accounts.tasks_retencja.sprzataj_retencje` | 03:45:01,399 | 1,393 s | dziennik, zaproszenia, sesje, MFA, rejestracje i powiadomienia: po 0 |
| F08 | `accounts.tasks_rezerwacje.czuwaj_nad_rezerwacjami` | 04:00:02,597 | 2,585 s | nierozliczone: 0; usunięte rozliczone: 0 |
| A04 | `documents.usuwanie_plikow.usun_oczekujace_pliki` | 10:15:36,900 | 1,282 s | 0; widoczne także wcześniejsze kolejne przebiegi co minutę |
| A02 | `accounts.tasks_stripe.uzgodnij_platnosci` | 10:11:35,696 | 0,438 s | sprawdzono: 0; wybrano: 0 |
| F15 | `accounts.tasks.send_password_notifications` | 10:15:35,997 | 0,458 s | 0 |

A02 nie przetestowano na prawdziwym powiązaniu ze Stripe: w tym odczycie
baza nie zawierała firm kwalifikujących się do kontroli. Nie oznaczamy
odbioru płatności ani alarmów jako zaliczonych.

## Bieżące kontrole tylko do odczytu

Na web wykonano standardowe komendy, bez opcji zmieniających dane:

| Komenda | Odczytany wynik |
|---|---|
| `kontrola_retencji` | Wszystkie okresy mieszczą się w 0–3650; niczego nie zmieniono |
| `check_message_reservations` | Brak nierozliczonych rezerwacji AI |
| `kontrola_usuwania_plikow` | Niezakończone zlecenia: 0 |
| `kontrola_stripe` | Firmy powiązane: 0; wymagające kontroli: 0 |
| `check_password_notifications` | `{"counts": {}, "overdue": 0}` |

Odczyt rejestru migracji o 10:18:48 CEST potwierdził:
`accounts.0041_proba_zakupu`, `accounts.0042_kontrola_stripe`,
`accounts.0043_usuwanie_retencja`, `chat.0008_usuwanie_retencja`,
`accounts.0044_trwale_usuwanie_plikow`,
`documents.0016_trwale_usuwanie_plikow`.

Ustawienie `TRUSTED_PROXY_DEPTH` na web wynosi 2. To potwierdzenie wartości
konfiguracji, nie test odporności na podrobiony nagłówek ani porównanie
adresu z rzeczywistym IP odwiedzającego. F07 zachowuje ten odbiór.
Ostrzeżenie `api.W002` odnotowane 30.09 na workerze nie wystąpiło
w poprzednich kontrolach web; sama różnica ról nie wymaga zmiany ustawień
produkcji podczas tego odczytu.

## Raport plików — wynik z 30.09.2026

Wynik został już wykonany na produkcji; tutaj zapisujemy go w repozytorium.
Nie przedstawiamy go jako nowego skanu z 1.10.

| Magazyn | Prefiksy | Sprawdzone | Powiązane | Do weryfikacji | Pełny zakres prefiksów |
|---|---|---:|---:|---:|---|
| `private_documents` | `private-documents/`, `documents/` | 1 | 1 (187 805 B) | 0 | tak |
| `default` | `widget_branding/`, `documents/` | 0 | 0 | 0 | tak |

Wszystkie pozostałe kategorie i niesklasyfikowane obiekty: 0. Błędy: brak.
Prywatne dokumenty: 16:31:01–16:31:02 CEST; default: 16:31:49–16:31:50 CEST.
Próbka wyłączona (`--probka 0`), bez nazw i treści plików. Skróty celów
obu magazynów były zgodne na web i workerze. Nie wykryto potrzeby sprzątania.

Pełny zakres oznacza wskazane prefiksy, nie całe buckety. Raport nie obejmuje
backupów, historycznych wersji obiektów, innych prefiksów, nieukończonych
uploadów wieloczęściowych ani CDN. Nie weryfikuje treści pliku i nie ma wspólnej
migawki bazy oraz magazynu. [Kontrakt raportu](raport-plikow-bez-odwolania.md).

## Co zamykamy, a co pozostaje

- F08: potwierdzenie automatycznego przebiegu wykonane. Brak rezerwacji
  wymagających decyzji w chwili kontroli; alarm z niezerową kolejką nie był
  w tym odbiorze wywoływany.
- F13/F20: potwierdzone zaplanowane przebiegi obu mechanizmów retencji.
  Nie wywoływano próbnego usuwania rzeczywistych danych.
- A01–A05: backend i wymagane migracje są wdrożone. Scenariusze biznesowe
  nie stają się odebrane tylko dlatego, że migracje i zadania działają.
- A04: wdrożenie, zgodność celów, pusty rejestr zaległości, automatyczny
  przebieg i raport plików potwierdzone. Nadal otwarte: usuwanie syntetycznych
  plików w rzeczywistym magazynie, alarm z potwierdzeniem odbioru,
  próba awarii w izolacji i odtworzenie zgodnej kopii z wstrzymaniem zleceń.
- A01/A02: nadal test mode Stripe, podwójny zakup, utracona odpowiedź,
  opóźnione zdarzenia, zmiana planu, odnowienie i alarm.
- A03/A05: nadal odbiór panelu/widgetu (410 i SSE), usuwanie w trakcie
  odpowiedzi na danych testowych oraz walidacja retencji przez rzeczywiste API.
- F15: pusta kolejka nie dowodzi doręczenia wiadomości. Odbiór poczty i ustawień
  bezpieczeństwa pozostaje otwarty.

## Następna kolejność

1. Dokończyć A04 na syntetycznych danych i w izolowanym środowisku awarii
   według [procedury A04](trwale-usuwanie-plikow-a04.md). Przed nieodwracalnym
   usunięciem w produkcji uzgodnić konkretne testowe obiekty; przed próbą
   poczty uzgodnić odbiorcę i treść. Nie pozbawiać produkcji dostępu do R2.
2. Wykonać odbiory A01/A02 w Stripe test mode oraz A03/A05 w panelu i widgecie.
3. Zamknąć pozostałe odbiory użytkownika: rejestracja, zaproszenia, upload,
   konta/MFA, sesje, reset hasła, pierwsze kroki, CSV oraz Turnstile.
4. Wykonać końcową macierz dostępu, skany zależności i środowiska produkcyjnego,
   pomiar obciążenia według uzgodnionego budżetu, dostępność oraz RTO usług.
5. Zebrać decyzje właściciela o SLO/SLA, warunkach sprzedaży i dokumentach
   prawnych. Nie traktować dokumentacji kodu jako potwierdzenia tych decyzji.

Nie dodano nowych usług ani kosztów stałych. Następny etap musi mieć zapisany
zakres danych testowych i mierzalny wynik; statusy ogólne pozostają w
[roadmapie](roadmapa-po-audycie.md).
