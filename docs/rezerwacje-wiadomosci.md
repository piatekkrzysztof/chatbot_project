# Rezerwacje wiadomości i ograniczenie kosztów AI (F08)

## Zasada rozliczenia

Trzy płatne endpointy (`/api/chat/`, `/api/widget/chat/`,
`/api/widget/chat/stream/`) przed wyszukiwaniem RAG i wywołaniem modelu
rezerwują jedno miejsce w pakiecie. PostgreSQL blokuje wiersz firmy tylko
na czas przyjęcia lub rozliczenia rezerwacji. Wywołania HTTP i generowanie
odpowiedzi odbywają się poza transakcją. Wszystkie procesy korzystają z tej
samej tabeli; poprawność miesięcznego limitu nie zależy od cache.

Do przyjęcia wiadomości musi zachodzić:
`rozliczone + pending + uncertain < message_limit` w bieżącym cyklu.
Licznik `current_message_count` nadal przedstawia rozliczone odpowiedzi.
Rezerwacje w toku nie są jeszcze zużyciem, ale zajmują dostępne miejsca.

- Odpowiedź modelu: `charged`, dokładnie jeden przyrost licznika.
- Awaria modelu bez odpowiedzi: `released`; miesięczny pakiet pozostaje bez zmian.
- Zamknięcie SSE po pierwszym fragmencie: wiadomość jest już naliczona,
  połączenie upstream zostaje zamknięte, częściowa odpowiedź zapisana.
- Zamknięcie SSE przed uruchomieniem generatora: rezerwacja jest zwalniana.
- Nieoczekiwany błąd lub zniknięcie procesu: `uncertain` (albo przeterminowane
  `pending`). Miejsce w pakiecie pozostaje zajęte do uzgodnienia wyniku.
- Reset pakietu zmienia UUID cyklu pod blokadą. Spóźnione rozliczenie starej
  rezerwacji nie zwiększa licznika nowego cyklu, także przy resecie tego samego dnia.

`finished` jest niezależne od naliczenia: pierwsza delta nalicza wiadomość,
ale miejsce w limicie równoległych wywołań jest zajęte do końca strumienia.
Rozliczenie jest idempotentne dla identyfikatora rezerwacji. Powtórzenie całego
POST przez klienta stanowi nową wiadomość; nie dodajemy tu kluczy idempotencji API.

## Limity

- Maksymalnie 10 aktywnych rezerwacji na firmę, łącznie dla czatu publicznego i testów.
- Atomowy limit prób w przesuwanym oknie 60 sekund według katalogu planów,
  obejmujący także nieudane i nieodebrane odpowiedzi. Cache DRF pozostaje
  dodatkową warstwą ograniczeń, a nie źródłem gwarancji.
- Czat testowy: 100 przyjętych prób na firmę na dobę UTC, bez zmniejszania
  płatnego pakietu; również próby nieudane wchodzą do budżetu testowego.
- Oba rodzaje czatu walidują długość pytania (`MAX_WIADOMOSC_ZNAKOW`, domyślnie 2000).
- Chat i embedding zapytania: timeout SDK 60 sekund, bez automatycznego retry.
- SSE sprawdza upływ 90 sekund między zdarzeniami. Timeout odczytu ogranicza
  oczekiwanie na kolejne zdarzenie. To nie jest twardy limit całego żądania
  HTTP ani czasu zapytań do PostgreSQL; zatrzymany proces wymaga nadzoru platformy.
- Rezerwacja wygasa po 10 minutach. Jej wygaśnięcie zwalnia blokadę współbieżności,
  ale nie zwraca automatycznie miejsca w pakiecie. Nieuruchomiony strumień
  nie może rozpocząć pracy po wygaśnięciu swojej rezerwacji.

Po przerwaniu odpowiedzi dostawca może nie wysłać końcowego licznika tokenów.
Liczba tokenów w historii może wtedy być niepełna; rozliczenie jednej wiadomości
nie zależy od otrzymania tego licznika. Zamknięcie połączenia nie gwarantuje,
że dostawca anuluje całą pracę już przyjętą po swojej stronie.

## Obsługa awarii

Kontrola jest domyślnie tylko do odczytu, z kodem błędu przy nierozliczonych
rezerwacjach; pokazuje maksymalnie 50 identyfikatorów, bez treści rozmów:

```sh
python manage.py check_message_reservations
```

Po sprawdzeniu logów i wyniku konkretnego wywołania operator uzgadnia **jedną
przeterminowaną** rezerwację. Nie wolno zbiorczo zwalniać niewyjaśnionych wywołań:

```sh
python manage.py check_message_reservations --reservation UUID --outcome charged
python manage.py check_message_reservations --reservation UUID --outcome released
```

Powtórzenie tej samej decyzji nie zmienia licznika. Komenda odrzuca zmianę
już zamkniętego wyniku oraz ingerencję przed upływem ważności rezerwacji.
Decyzję i uzasadnienie należy zapisać w zgłoszeniu incydentu.

Usuwanie rozliczonych rezerwacji starszych niż 90 dni (bez bieżącego cyklu
i bez stanów niewyjaśnionych):

```sh
python manage.py check_message_reservations --prune
```

## Kto to wszystko uruchamia (2.16.0)

Do 2.16.0: **nikt.** Powyższe komendy istniały od #44 i działały, ale nie było
ich w żadnym harmonogramie ani alarmie. Przez cały ten czas nie policzył
nierozliczonych biletów ani nie usunął starych rozliczonych ani jeden przebieg.

To o stopień gorszy wariant awarii z 2.14.1. Tamte trzy zadania były
w harmonogramie i beat je zlecał, więc worker zostawiał w logu
`Received unregistered task` - ślad, po którym dało się je znaleźć. Tutaj nie
było czego znaleźć: brak wpisu nie zostawia śladu nigdzie.

Od 2.16.0 codziennie o 4:00 robi to zadanie
`accounts.tasks_rezerwacje.czuwaj_nad_rezerwacjami` na istniejącym workerze
(bez nowej usługi i bez nowego crona). Zadanie:

1. liczy bilety do rozliczenia i przy niezerowej liczbie wysyła alert na
   `EMAIL_ALERTOW` z listą i gotowymi komendami,
2. usuwa bilety rozliczone dawniej niż 90 dni,
3. zapisuje obie liczby w logu **także przy zerach** - cisza w logu nie
   odróżnia przebiegu, który nic nie znalazł, od przebiegu, którego nie było.

Potwierdzenie przebiegu: **zakładka Stan w panelu**, karta „Rozliczanie pracy
bota". Pokazuje liczbę wiadomości czekających na rozliczenie i liczbę biletów,
które przekroczyły termin sprzątania. Od 2.19.0, bo do tego czasu wynik tego
zadania dało się zobaczyć wyłącznie w logu usługi `celery-worker` - a log, do
którego trzeba zejść, nie jest kontrolą. Tę samą lekcję zapisał już raport
z incydentu 26.08.2026: „A step on a checklist a person walks through is not
detection."

W logu workera ta sama informacja wygląda tak i zostaje przydatna przy
diagnozowaniu pojedynczego przebiegu:

```text
Rezerwacje: do rozliczenia 0, usuniętych rozliczonych 0
```

### Czego karta w panelu nie potwierdza

Zadanie robi dwie rzeczy, a z bazy widać jedną. **Sprzątanie** zostawia ślad:
bilet rozliczony dawniej niż 90 dni, który wciąż leży, dowodzi, że zadanie nie
przebiegło. **Wysyłki alarmu nie widać wcale** - karta nie udaje, że wie, czy
poczta wyszła.

Przy pustej albo młodej tabeli karta mówi „nie da się potwierdzić", a nie
„działa". Bilet, którego nie ma czego kasować, nie jest dowodem na nic - to ta
sama zasada, która obowiązuje przy retencji rozmów.

Czego zadanie NIE robi: nie rozlicza niczego samo. Stan `uncertain` znaczy
dokładnie tyle, że nie wiemy, czy zapytanie doszło do OpenAI. Automat musiałby
zgadnąć - obciążyć klienta za pracę, której mogło nie być, albo darować pracę,
za którą mogliśmy zapłacić. Zgadywanie jest gorsze od czekania, bo nikt się
o nim nie dowie. Decyzja zostaje przy człowieku i przy komendzie wyżej.

Alert przychodzi codziennie, dopóki jest co rozliczać. Nie ma tu znacznika
„zgłoszone" jak przy odmowach widgetu: tam znacznik chroni przed powtarzaniem
tej samej przyczyny co godzinę, tutaj każdy bilet to osobna decyzja i dopóki
jej nie ma, sprawa nie jest załatwiona.

## Wdrożenie i odbiór

Migracja `accounts.0032_message_reservations` dodaje UUID cyklu i nową tabelę
z indeksami; nie zeruje istniejącego zużycia. Standardowy start aplikacji
wykonuje migracje. Po wdrożeniu sprawdzić commit web/worker i `/health/` (2.0.4),
następnie wykonać test na wydzielonej firmie testowej: ostatnia wiadomość,
równoległe żądanie, błąd modelu, przerwanie SSE i bezpłatny test bota.
Podczas wymiany procesów stary kod nadal może działać bez rezerwacji — pełna
gwarancja obowiązuje po zakończeniu starych procesów i żądań.

Lokalne testy używają oddzielnego PostgreSQL i atrap AI bez dostępu do produkcji.
Pełny test produkcyjnej ścieżki i pomiar obciążenia nie są zastępowane przez CI.
