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

Usuwanie rozliczonych rezerwacji starszych niż 90 dni (do 1000 na wykonanie,
bez bieżącego cyklu i stanów niewyjaśnionych):

```sh
python manage.py check_message_reservations --prune
```

Podpięcie kontroli do harmonogramu, alertów i retencji pozostaje zadaniem
operacyjnym. Ten PR nie uruchamia harmonogramu ani nie zmienia Rendera.

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
