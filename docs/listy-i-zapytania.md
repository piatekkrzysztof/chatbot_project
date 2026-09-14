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

---

# F16, część 2 - listy wiedzy, publiczne FAQ i eksport CSV

**Wersja:** 2.4.0. **Zakres:** `api/views/documents.py`, `api/views/faq.py`,
`api/views/widget.py`, `api/views/chat_csv.py`, `chat/eksport_csv.py`,
`chat/admin.py`; panel: Baza wiedzy i FAQ.

**Wdrożenie:** bez migracji, najlepiej razem z panelem. Obecny panel przyjmie
odpowiedź ze stronami, ale pokaże tylko pierwsze 50 dokumentów i wpisów FAQ,
bez przycisków stron.

## Co było nie tak

| Lista | Dlaczego rośnie | Skutek |
|---|---|---|
| Dokumenty | import strony zakłada dokument na każdą podstronę (do 20 na źródło), źródeł nie ogranicza plan | setki pozycji przy każdym wejściu w Bazę wiedzy |
| FAQ | wpisy dodaje się ręcznie, bez górnej granicy | cała lista przy każdym wejściu |
| `/api/widget/faq/` | publiczny endpoint, sam klucz z kodu widgetu | całe FAQ firmy jednym żądaniem dla każdego, kto zna klucz |
| Eksport CSV | cała historia rozmów | `HttpResponse` zbierał plik w pamięci procesu przed wysłaniem |

Źródła stron, użytkownicy i zaproszenia zostają bez stron: pierwsze dodaje się
ręcznie pojedynczo, dwa pozostałe ogranicza limit miejsc w planie.

## Jak jest teraz

1. **Dokumenty i FAQ stronami** (`StronicowaniePanelu`, 50, maks. 200), od
   najnowszych. Panel: nowy dokument i nowy wpis FAQ na pierwszej stronie;
   usunięcie ostatniego wpisu FAQ na dalszej stronie cofa o jedną (inaczej 404).
2. **Publiczne FAQ widgetu** zwraca najwyżej `MAKS_FAQ_WIDGETU = 100` pierwszych
   wpisów (w kolejności dodania, jak dotąd).
3. **Eksport CSV strumieniem** (`strumien_csv`): wiersz po wierszu, historia
   czytana porcjami po 1000 wierszy. BOM, nagłówek i neutralizacja formuł bez
   zmian. Tak samo eksport z panelu administracyjnego.

## Świadome ograniczenia

- Test pilnuje, że eksport jest strumieniem, ma tę samą treść i nie robi zapytań
  na wiersz. Zużycie pamięci nie jest mierzone wprost.
- Nazwa pobieranego pliku i kolumny eksportu bez zmian.

## Weryfikacja

`api/tests/test_wiedza_i_eksport.py`: 6 testów. Zmienione oczekiwania istniejących
testów: eksport czytany ze strumienia (`test_csv_i_oceny.py`, `test_chat_csv.py`,
`test_access_boundaries.py`), listy FAQ i dokumentów z `results`
(`test_analytics_faq.py`, `test_wydajnosc_list.py`).

**Odtworzenie:** na kodzie sprzed zmiany czerwienieje 6 z 6. Cztery odtwarzają
błąd (dokumenty i FAQ bez stron, publiczne FAQ bez limitu, eksport w pamięci).
Dwa pozostałe - treść strumienia i brak zapytań na wiersz - to straże; na starym
kodzie padają tylko dlatego, że odpowiedź nie była strumieniem.

**Mutacje** (14.09.2026): 9 z 9 uszkodzeń czerwieni co najmniej jeden test -
dokumenty i FAQ bez stron oraz od najstarszych, publiczne FAQ bez limitu, eksport
w pamięci, bez neutralizacji formuł, bez BOM, zapytanie o rozmowę na wiersz
eksportu.

Testy powiązane: 291 passed. Panel: 3 nowe testy, vitest 142/142, `tsc`
i eslint czyste.
