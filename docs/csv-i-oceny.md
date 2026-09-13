# F19 - poprawne CSV i integralność ocen

**Zakres:** `chat/eksport_csv.py` (nowy), `api/views/chat_csv.py` (eksport
i import), `chat/admin.py` (eksport w panelu administracyjnym),
`chat/zapytania.py` (co jest ruchem klientów), `documents/uploads.py`
i `CSV_IMPORT_MAX_UPLOAD_BYTES` (limit importu), `api/views/feedback.py`
(oceny), `api/schemas.py` (opis pola), widget w `chatbot-frontend`
(`components/widget/WidgetChat.tsx`).

**Nie zmienia:** schematu bazy (bez migracji), usług, planów ani limitów czatu.

**Wdrożenie:** najpierw frontend (widget wysyła sesję przy ocenie,
piatekkrzysztof/frontend_chatbot#16), potem web
i worker backendu z tym samym commitem. Odwrotna kolejność: oceny ze starej
wersji widgetu są odrzucane, a widget połyka błąd, więc rozmowa działa, ale
ocena przepada do odświeżenia strony.

---

## Co było zepsute

### Eksport

| # | Sytuacja | Skutek |
|---|---|---|
| 1 | Odwiedzający wpisuje w widgecie tekst zaczynający się od `=`, `+`, `-`, `@`, tabulatora albo powrotu karetki | Po otwarciu eksportu w arkuszu komórka działała jak formuła: aktywny link albo polecenie (DDE). Dotyczyło eksportu w API i w panelu administracyjnym |
| 2 | Choć jedna rozmowa firmy usunięta w ramach retencji (`conversation` = NULL) | `log.conversation.id` - cały eksport firmy kończył się błędem 500 |
| 3 | Eksport otwierany w Excelu na polskim Windowsie | Bez BOM Excel czytał plik jako Windows-1250 - krzaczki zamiast polskich liter |

### Import

| # | Sytuacja | Skutek |
|---|---|---|
| 4 | Błąd kodowania albo składni w połowie pliku | Wiersze zapisywały się w trakcie czytania: połowa pliku w bazie i błąd 500. Ponowienie dublowało zapisaną część |
| 5 | Plik z BOM - tak zapisuje Excel „CSV UTF-8" | Nagłówek czytał się jako `﻿prompt`, import zapisywał zero wierszy i zwracał 201 |
| 6 | Nagłówek bez kolumn `prompt` i `response` | 201 i „imported: 0" - wyglądało na udany import |
| 7 | Dwie rozmowy importu w bazie (np. po dwóch importach naraz) | `get_or_create` rzucał `MultipleObjectsReturned`: każdy kolejny import kończył się 500 |
| 8 | Duży plik | Brak limitu bajtów i wierszy |
| 9 | Zaimportowana historia | Liczyła się jako ruch klientów na pulpicie. Źródło `imported` nie ma nawet miejsca na liście źródeł odpowiedzi |

### Oceny

| # | Sytuacja | Skutek |
|---|---|---|
| 10 | Ocena z widgetu | Klucz API widgetu jest publiczny, a wystarczał numer wiadomości - każdy mógł ustawić oceny wszystkich odpowiedzi firmy, licząc kolejne numery |
| 11 | Ocena z panelu | Członek zespołu, także w roli `viewer`, nadpisywał ocenę wystawioną przez odwiedzającego. Wiadomość ma jedną ocenę |

## Jak jest teraz

1. **Neutralizacja formuł według OWASP** (CSV Injection): komórka tekstowa
   zaczynająca się od znaku formuły dostaje z przodu apostrof. Wspólny moduł
   `chat/eksport_csv.py` dla obu eksportów. Liczby bez zmian.
2. **BOM na początku eksportu.**
3. **Eksport pisze `conversation_id`**, więc wpis po retencji ma pustą
   komórkę, a przy okazji nie ma zapytania o rozmowę dla każdego wiersza.
4. **Import czyta i sprawdza cały plik przed zapisem**, a zapis idzie w jednej
   transakcji. UTF-8 z BOM i bez. Brak wymaganych kolumn, zła składnia, złe
   kodowanie, ponad 5000 wierszy - 400 z komunikatem i nic nie zapisane.
5. **Limit 2 MiB liczony w trakcie odbioru**, tym samym mechanizmem co upload
   dokumentów (413).
6. **Rozmowa importu:** pierwsza istniejąca albo nowa, z `source="imported"`.
7. **Import poza statystykami:** `logi_klientow` pomija wpisy `imported`,
   `rozmowy_klientow` - rozmowy importu (także starsze, rozpoznawane po
   `user_identifier`). Eksport CSV nadal je zawiera (`logi_do_eksportu`):
   to kopia danych firmy, a import i eksport tworzą parę.
8. **Ocena z widgetu wymaga `conversation_session_id`** rozmowy, do której
   należy wiadomość. Odmowa ma ten sam komunikat co nieistniejąca wiadomość,
   żeby nie zdradzać, które numery istnieją.
9. **Panel ocenia wyłącznie rozmowy testowe.** Prawdziwe rozmowy ocenia
   odwiedzający.

## Sprawdzone i bez zmian

**Dwie pierwsze oceny tej samej wiadomości naraz.** Podejrzenie
`IntegrityError` z `update_or_create` na polu jeden-do-jednego się nie
potwierdziło: w Django 5.2 `update_or_create` idzie przez `get_or_create`,
który po `IntegrityError` odczytuje istniejący wiersz. Bez poprawki.

## Świadome ograniczenia

- **Starsze wpisy importu mają źródło spoza listy wyborów.** Dodanie wartości
  do listy to migracja stanu; pełne odtworzenie kopii wymaga zgodnego stanu
  migracji, więc bez niej. Wpisy są rozpoznawane po wartości `imported`.
- **Apostrof widać** przy czytaniu eksportu programem, który nie jest
  arkuszem, i w tekstach zaczynających się od myślnika (np. „- a cena?").
  To koszt zalecanej neutralizacji.
- **Eksport nadal buduje całą odpowiedź naraz.** Strumieniowanie dużych
  eksportów należy do F16.
- **Czat testowy w panelu nie pokazuje kciuków** - endpoint panelowy jest
  gotowy, ale frontend go dziś nie woła.

## Weryfikacja

Nowy plik `api/tests/test_csv_i_oceny.py`, 24 przypadki.

**Odtworzenie błędu:** na kodzie sprzed zmiany czerwienieje 21 z nich - każdy
odtwarza błąd z tabel wyżej. Trzy przechodzą także na starym kodzie i to są
straże: zwykły tekst i liczby w eksporcie bez zmian, ocena własnej rozmowy
w widgecie, ocena rozmowy testowej w panelu.

**Weryfikacja mutacyjna** (13.09.2026): każde z piętnastu uszkodzeń
czerwieni co najmniej jeden test - bez neutralizacji formuł, bez BOM, eksport
przez `conversation.id`, eksport administracyjny zwykłym `csv.writer`,
przepuszczenie błędu kodowania, bez sprawdzenia kolumn, bez limitu wierszy,
nieobsłużony `csv.Error`, `get_or_create` rozmowy importu, bez limitu rozmiaru,
import liczony w logach i w rozmowach, eksport pomijający import, widget bez
sesji, panel oceniający każdą rozmowę.

**Poprawka po CI:** pierwsza wersja wykluczała import także z eksportu.
CI wyłapało to testem `test_csv_round_trip_works_with_jwt_alone` (import,
potem eksport tego samego). Eksport jest kopią danych firmy, a nie statystyką,
więc dostał własne zapytanie `logi_do_eksportu`; poza statystykami import
zostaje przez `logi_klientow`.

Powiązane pakiety (oceny, CSV, eksport administracyjny, logi, czat testowy,
uploady, retencja, role): 167 passed. Frontend: `tsc`, `eslint`, `vitest`
72 passed.

Zmienione oczekiwania istniejących testów: testy oceny z panelu używają rozmów
testowych, testy oceny z widgetu wysyłają sesję rozmowy.

## Co sprawdzić po wdrożeniu

1. Widget: kciuk przy odpowiedzi zapisuje ocenę (panel, logi rozmów, filtr
   „pomocne").
2. Eksport CSV otwarty w Excelu: polskie litery poprawne; wiadomość
   zaczynająca się od `=` widoczna jako tekst.
3. Import próbnego pliku z Excela („CSV UTF-8"): liczba zaimportowanych
   wierszy zgodna z plikiem; pulpit bez zmian w liczbie rozmów.
