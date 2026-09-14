# F16, część 1 - listy panelu: zapytania do bazy i stronicowanie

**Wersja:** 2.3.0. **Zakres:** `api/pagination.py` (nowy), `api/views/chat_logs.py`,
`api/views/contact.py`, `api/views/documents.py`, `api/serializers.py`,
`api/views/dziennik.py`; panel: Konwersacje i Zapytania.

**Wdrożenie:** bez migracji. Backend i panel w dowolnej kolejności - obecny panel
już przyjmuje odpowiedź ze stronami (`results`), a nowy panel wyświetla też zwykłą
listę.

---

## Pomiar (14.09.2026)

Firma z 3 i z 30 obiektami każdego rodzaju (dokumenty z fragmentami, źródła stron,
FAQ, rozmowy z ocenami, historia, zapytania, zaproszenia, witryny, dziennik,
pracownicy). Dla każdej listy panelu: kod odpowiedzi, liczba zapytań SQL, długość.

| Lista | 3 obiekty | 30 obiektów | Wniosek |
|---|---|---|---|
| `/api/documents/` | 9 zapytań | **63 zapytania** | N+1: liczenie i sprawdzanie fragmentów dla każdego dokumentu |
| `/api/chat/logs/` | 6 | **33** | N+1: ocena szukana osobno dla każdego wpisu; do tego cała historia bez stron |
| `/api/contact-requests/` | 3, lista 3 | 3, **lista 30** | stała liczba zapytań, ale cała historia bez stron |
| `/api/users/`, `/api/website-sources/`, `/api/faq/`, `/api/accounts/invitations/list/`, `/api/widget/faq/` | 3 | 3 | stała liczba zapytań; listy bez limitu - część 2 |
| `/api/accounts/dziennik/` | 4, strona | 4, strona | już stronicowany |
| `/api/knowledge/`, `/api/analytics/`, `/api/privacy/`, `/api/billing/plans/`, `/api/chat/export/` | 2-10 | bez zmian | stała liczba zapytań |

Historia rozmów miała `pagination_class = PageNumberPagination`, ale bez
`page_size` DRF nie stronicuje niczego i o tym nie informuje.

## Jak jest teraz

1. **Stała liczba zapytań.** Dokumenty dostają liczbę fragmentów w tym samym
   zapytaniu (`annotate(liczba_fragmentow=Count("chunks"))`), historia rozmów -
   ocenę jednym podzapytaniem (najstarsza wiadomość bota tej rozmowy z tą samą
   treścią, jak dotąd). Serializery korzystają z dołączonych wartości, a bez nich
   (np. przy pojedynczym dokumencie po wgraniu) liczą jak wcześniej.
2. **Test stałej liczby zapytań** (`api/tests/test_wydajnosc_list.py`) obejmuje
   12 list i ekranów panelu: ta sama liczba zapytań przy 3 i przy 30 obiektach.
   Nowe pole liczone w pętli po wierszach czerwieni test, zanim trafi na produkcję.
3. **Stronicowanie** `StronicowaniePanelu`: 50 na stronę, `?rozmiar=` do 200.
   Historia rozmów i zapytania kontaktowe od najnowszych. Dziennik korzysta
   z tej samej klasy.
4. **Licznik nieobsłużonych** w odpowiedzi listy zapytań (`nieobsluzone`) obejmuje
   wszystkie strony. Panel liczył go dotąd z wczytanej listy - po stronicowaniu
   pokazywałby liczbę z jednej strony.
5. **Filtr ocen w historii** (`?is_helpful=`) korzysta z oceny tej samej rozmowy.
   Wcześniej porównywał odpowiedź z treścią ocenionych wiadomości ze wszystkich
   firm: identyczna odpowiedź oceniona u kogoś innego trafiała na listę, a
   podzapytanie rosło z liczbą ocen w całym systemie.
6. **Panel:** Konwersacje i Zapytania stronami („Nowsze" / „Starsze", liczba
   wpisów łącznie), jak w Dzienniku. Oznaczenie zapytania wczytuje od nowa tę samą
   stronę.

## Świadome ograniczenia

- Dokumenty, FAQ, źródła stron, użytkownicy, zaproszenia i publiczne FAQ widgetu
  nadal zwracają całą listę - rosną wolniej i ograniczają je limity planu
  (baza wiedzy w MB, miejsca, witryny). Część 2.
- Eksport CSV nadal buduje całą odpowiedź naraz - część 2.
- Czas odpowiedzi nie jest jeszcze mierzony na produkcji; test pilnuje liczby
  zapytań, nie milisekund - część 3.

## Weryfikacja

`api/tests/test_wydajnosc_list.py`: 8 testów. Zmienione oczekiwania istniejących
testów: `test_chat_logs.py` i `test_contact_requests.py` czytają wpisy z `results`.

**Odtworzenie:** na kodzie sprzed zmiany czerwienieje 7 z 8. Test stałej liczby
zapytań sam wskazuje rosnące listy (dokumenty 9 → 63, historia rozmów). Zielony
zostaje test statusu dokumentu - straż, że dołączona liczba fragmentów nie zmienia
statusów `ready` / `processed_no_chunks` / `processing`.

**Mutacje** (14.09.2026): 10 z 10 uszkodzeń czerwieni co najmniej jeden test -
historia bez stron i od najstarszych, ocena w pętli po wierszach, pominięty filtr
ocen, liczba fragmentów w pętli, zapytania bez stron i od najstarszych, licznik
nieobsłużonych z bieżącej strony, brak górnego limitu strony, status bez
sprawdzenia fragmentów.

Testy powiązane (dokumenty, dziennik, historia, zapytania, role, czat testowy,
limity, schemat OpenAPI): 245 passed. Panel: 5 nowych testów stronicowania,
vitest 139/139, `tsc` i eslint czyste.
