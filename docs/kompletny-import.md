# F10, część 1 - kompletny import wiedzy ze strony klienta

**Zakres:** `documents/website_import.py`, `documents/sitemaps.py`,
`documents/safe_http.py` (nowa klasa błędu `ResponseTooLarge`),
`documents/tasks.py` (kolejność podstron w zadaniu pobierania).

**Nie zmienia:** schematu bazy (bez migracji), zmiennych środowiskowych, usług,
limitów (20 podstron na źródło, 2 MiB na odpowiedź, budżet żądań i czasu),
panelu ani uploadu plików.

**Wdrożenie:** web i worker z tym samym commitem. Pobieranie stron działa
w workerze, a przy niedostępnym brokerze także w procesie web.

---

## Dlaczego to ważne

Strona klienta to druga, obok plików, droga budowania wiedzy - i ta, której
klient nie kontroluje w szczegółach. Wszystkie usterki poniżej były ciche:
pobieranie kończyło się sukcesem, a panel pokazywał „gotowe".

## Co było zepsute

| # | Sytuacja | Skutek |
|---|---|---|
| 1 | Link do zdjęcia na stronie (galeria, logo w linku) | Zdjęcie przechodziło przez ekstrakcję HTML. PNG 270 KB dawał **226 986 znaków** zdekodowanych bajtów, JPG 56 KB - 48 371. Trafiały do wiedzy, do limitu planu i do płatnych embeddingów |
| 2 | Cennik w PDF podlinkowany na stronie | Do wiedzy trafiała składnia pliku (`%PDF-1.3 ... obj`), nie jego tekst |
| 3 | Galeria z dwudziestoma zdjęciami przed linkiem do oferty | Limit 20 adresów wypełniały zdjęcia, oferta nie trafiała nawet do kolejki |
| 4 | Jeden podlinkowany plik ponad 2 MiB | Przekroczenie rozmiaru było tym samym błędem co wyczerpany budżet, więc przerywało **całe** pobieranie źródła |
| 5 | Mapa strony ponad 2 MiB (sklep z tysiącami produktów) | To samo: całe pobieranie przerwane, zamiast przejść do wyszukiwania po linkach |
| 6 | WordPress z Yoast: mapa wpisów przed mapą stron | Dwadzieścia wpisów blogowych zajmowało limit, cennik i kontakt nie trafiały do wiedzy |
| 7 | WordPress bez wtyczki: mapa stron piąta w indeksie | Limit pięciu plików map obcinał ją - nie była nawet pobierana |
| 8 | Klient dodaje konkretną podstronę, np. `/cennik` | Gdy mapa strony istniała, pobierano wyłącznie jej adresy. Podstrona podana przez klienta mogła nie trafić do wiedzy nigdy |
| 9 | Strona główna pobrana kiedyś po linkach, dziś strona ma mapę | `https://firma.pl` i `https://firma.pl/` dawały dwa dokumenty z tą samą treścią; stary zostawał na zawsze |

## Jak jest teraz

1. **Typ treści decyduje o ścieżce.** HTML idzie przez dotychczasową
   ekstrakcję. PDF, DOCX, TXT i MD - przez ten sam izolowany parser co upload
   w panelu, z tymi samymi limitami. Każdy inny typ kończy pobranie tej
   podstrony błędem „Nieobsługiwany typ treści", widocznym w panelu przy
   źródle. Brak nagłówka typu albo `octet-stream`: PDF i DOCX rozpoznajemy po
   zawartości, dane binarne odrzucamy, resztę jak dotąd traktujemy jako HTML.
2. **Linki do plików bez treści pomijamy przed pobraniem** (obrazy, wideo,
   archiwa, style, skrypty, formaty biurowe spoza obsługiwanych). Nie zajmują
   miejsc na podstrony ani żądań z budżetu.
3. **Za duża pojedyncza odpowiedź dotyczy tylko jej adresu**
   (`ResponseTooLarge`). Wyczerpany budżet źródła nadal przerywa pobieranie,
   jak dotąd.
4. **Adres źródła jest pobierany zawsze i jako pierwszy.**
5. **Mapy stron stałych przed wpisami i taksonomiami.** Rozpoznajemy je po
   nazwie pliku według konwencji WordPressa, Yoast, Rank Math, Shopify i Wix
   (`page-sitemap.xml`, `wp-sitemap-posts-page-1.xml`, `sitemap_pages_1.xml`).
   Mapy tagów, kategorii i autorów idą na koniec. Mapy bez rozpoznanej nazwy
   dzielą limit po równo, zamiast oddawać go pierwszej w kolejności.
6. **Ta sama podstrona w innej pisowni** trafia do istniejącego dokumentu.

## Świadome ograniczenia

- **Limit 20 podstron na źródło zostaje.** Zmienia się tylko to, które
  podstrony się w nim mieszczą. Większy limit to więcej żądań do strony
  klienta i więcej embeddingów - decyzja cenowa, nie poprawka.
- **Priorytet map to podpowiedź z nazwy pliku**, nie pomiar treści. Mapa
  nazwana nietypowo dostaje równy udział, nie gorszy.
- **Import strony nie odróżnia strony w przebudowie od prawdziwej zmiany.**
  Strona „Wkrótce wracamy" z ponad stu znakami treści zastąpi poprzednią
  wersję. Pusta strona - nie: pobranie poniżej progu kończy się błędem przed
  zapisem.
- **Podstrona usunięta ze strony klienta zostaje w wiedzy.** Usuwanie danych
  pochodnych to F18, a roadmapa odkłada automatyczne usuwanie do odbioru
  pełnego odtworzenia z kopii.
- **Discovery nadal pobiera stronę dwa razy** (raz szukając linków, raz
  importując). Przy wolnej stronie budżet czasu 120 s może skończyć się przed
  ostatnimi podstronami - import zapisze wtedy częściowy błąd przy źródle.

## Sprostowanie do F17

Opis F17 (`docs/atomowa-publikacja-wektorow.md`) i komentarz w zadaniu
twierdziły, że pusta strona z importu nadpisuje treść dokumentu. To było
nieprawdziwe: `fetch_text_from_url` odrzuca treść poniżej progu przed zapisem.
Oba miejsca poprawione, a test
`test_pusta_strona_nie_nadpisuje_istniejacej_tresci` pilnuje, żeby tak zostało.

## Weryfikacja

Nowy plik `documents/tests/test_kompletny_import.py`, 22 przypadki.

**Odtworzenie błędu:** na kodzie sprzed zmiany czerwienieje 16 z nich. Sześć
przechodzi także na starym kodzie i to jest zamierzone - to straże: HTML
z nagłówkiem i bez, zwykły tekst, pusta strona, wyczerpany budżet i jedna
z dwóch pisowni adresu.

**Weryfikacja mutacyjna** (13.09.2026): każde z trzynastu celowych uszkodzeń
czerwieni co najmniej jeden test - przepuszczenie nieobsługiwanego typu,
usunięcie mapy typów plików, rozpoznania PDF po zawartości i wykrycia bajtów
binarnych, pobieranie linków do obrazów, przerwanie wyszukiwania i map przez
jedną za dużą odpowiedź, brak kolejności priorytetu w indeksie map, brak
pierwszeństwa map stron stałych, brak podziału limitu między mapy, pominięcie
adresu źródła, ignorowanie pisowni istniejącego dokumentu oraz zgłaszanie
rozmiaru jako wyczerpanego budżetu. Dwie ostatnie pierwsza wersja testów
przepuszczała - stąd test `test_strony_stale_maja_pierwszenstwo_nie_tylko_rowny_udzial`
i zaostrzony `test_wire_and_decoded_limits`.

Zmienione oczekiwania istniejących testów, wprost wynikające z punktu 4:
trzy testy zadania pobierania liczą o jedną podstronę więcej (adres źródła),
test ataku prefiksem domeny oczekuje pobrania źródła i `/faq`, a test „wszystkie
linki poza domeną" dostał mock importu - bez niego po zmianie sięgał do
prawdziwej sieci. `test_wire_and_decoded_limits` wymaga teraz `ResponseTooLarge`.

## Co sprawdzić po wdrożeniu

1. Na wydzielonej firmie dodać źródło z WordPressem z blogiem: w dokumentach
   pojawiają się strona główna, oferta i kontakt, nie same wpisy.
2. Strona z podlinkowanym PDF: dokument z tekstem PDF, bez `%PDF` w treści
   (panel, podgląd fragmentów).
3. Pulpit, „Wiedza, którą zna bot": przy starych źródłach nie przybywa kopii
   strony głównej po odświeżeniu.

# F10, część 2 - pliki i limit wiedzy przy równoległych dodaniach

**Zakres:** `documents/validators.py` (`zablokuj_baze_wiedzy`),
`api/views/documents.py` (upload), `documents/tasks.py` (odczyt pliku w tle),
`documents/website_import.py` (import strony), `documents/signals.py`
(zlecanie zadań), `documents/file_limits.py` (TXT i DOCX).

**Nie zmienia:** schematu bazy (bez migracji), zmiennych, usług, limitów planów.

**Wdrożenie:** web i worker z tym samym commitem.

## Co było zepsute

| # | Sytuacja | Skutek |
|---|---|---|
| 1 | Dwa uploady naraz, każdy mieści się w limicie sam | Oba mierzyły bazę przed zapisem drugiego i oba się zapisywały - razem ponad limit planu. To samo przy równoległym odczycie plików w tle i pobieraniu stron |
| 2 | Zapis dokumentu w transakcji | Sygnał zlecał zadanie przed zatwierdzeniem. Szybki worker nie widział jeszcze dokumentu, a zadanie embeddingów po F17 kończy się wtedy po cichu - dokument zostawał bez fragmentów. Zanim poprawka 1 objęła zapis transakcją, dotyczyło to zapisu z panelu administracyjnego Django, który zapisuje w transakcji; po niej dotyczyłoby każdego uploadu |
| 3 | TXT w Windows-1250, ISO-8859-2 albo UTF-16 | Odrzucany jako „nie UTF-8", choć tekst był poprawny |
| 4 | Tabela w DOCX | Każda komórka osobną linią: usługa i cena w różnych fragmentach |
| 5 | Pole tekstowe w DOCX | Tekst w wiedzy dwa razy (wersja nowa i zapasowa zapisywane przez Worda) |
| 6 | Pozycje tabulatorów w akapicie DOCX | Zbędne znaki tabulacji w treści |

## Jak jest teraz

1. **Sprawdzenie limitu i zapis pod blokadą bazy wiedzy firmy**, na wszystkich
   trzech drogach dodawania wiedzy. Pobranie pliku albo strony i parsowanie
   trwają poza blokadą. Zastępowaną treść (odświeżana podstrona, ponownie
   czytany plik) czytamy pod blokadą.
2. **Blokada doradcza PostgreSQL, nie blokada wiersza firmy.** Wiersz firmy
   blokuje rezerwacja wiadomości czatu. Upload trzyma blokadę także podczas
   zapisu pliku do magazynu, więc blokada wiersza firmy wstrzymywałaby
   rozmowy w widżecie na czas każdego uploadu. Test pilnuje, że rezerwacja
   wiadomości przechodzi, gdy blokada bazy wiedzy jest zajęta.
3. **Zadania zlecane po zatwierdzeniu transakcji** (`transaction.on_commit`).
   Wycofany zapis nie zleca niczego. Poza transakcją zachowanie bez zmian.
4. **TXT i MD:** UTF-8, UTF-16 ze znacznikiem BOM, Windows-1250 i ISO-8859-2.
   Między dwoma ostatnimi rozstrzyga liczba polskich liter (przy remisie
   Windows-1250). Wariant ze znakami sterującymi C1 odpada - bez tego bajty
   bez znaczenia w żadnym kodowaniu przechodziły jako tekst z niewidocznymi
   znakami. Dane binarne dalej są odrzucane.
5. **DOCX:** wiersz tabeli w jednej linii (`Strzyżenie | 50 zł`), także
   wiersze w kontrolkach treści; tekst pól tekstowych raz; właściwości
   akapitów i przebiegów pomijane.

## Świadome ograniczenia

- **Plik zapisany w magazynie przy wycofanej transakcji zostaje w magazynie.**
  Wycofanie po zapisie pliku zdarza się tylko przy awarii bazy między zapisem
  pliku a zatwierdzeniem. Usuwanie osieroconych plików to F18/F19.
- **UTF-16 bez znacznika BOM i inne kodowania** (np. CP852 z DOS-a) nadal są
  odrzucane z komunikatem, żeby zapisać plik w UTF-8.
- **Pusty plik UTF-16 z samym znacznikiem BOM** nie jest już błędem kodowania;
  upload i odczyt w tle odrzucają go jako plik bez tekstu, tak jak pusty UTF-8.
- **Wybór kodowania to rozstrzygnięcie po literach**, nie pewność. Tekst bez
  ani jednej z liter ą, ś, ź, Ą, Ś, Ź wygląda tak samo w obu kodowaniach,
  więc wybór nie ma wtedy znaczenia.

## Weryfikacja

Nowy plik `documents/tests/test_import_plikow_i_limit.py`, 20 przypadków.
Równoległość odtwarzana deterministycznie: bramka wstrzymuje oba dodania po
pomiarze bazy, a przy działającej blokadzie drugie dodanie czeka na blokadzie
i bramka rozpada się po 1,5 s.

**Odtworzenie błędu:** na kodzie sprzed zmiany czerwienieje 18 z 20, ale
realnie odtwarza błąd 15: trzy równoległe dodania, dwa zlecenia przed
zatwierdzeniem, pięć przypadków kodowania, pięć DOCX. Trzy pozostałe
czerwienieją, bo sprawdzają rzeczy, których nie było (funkcja blokady) albo
inny komunikat dla pliku, który stary kod też odrzucał. Dwa przechodzą na
starym kodzie - straże UTF-8 i danych binarnych.

**Weryfikacja mutacyjna** (13.09.2026): każde z trzynastu uszkodzeń czerwieni
co najmniej jeden test - usunięcie blokady doradczej, blokada wiersza firmy
zamiast doradczej, upload, odczyt w tle i import strony bez blokady,
zlecanie embeddingów przed zatwierdzeniem, bez UTF-16, bez liczenia polskich
liter, bez filtra znaków C1, pole tekstowe z wersją zapasową, czytanie
właściwości akapitu, tabela bez wierszy, wiersze w kontrolkach treści.
Filtra C1 nie było w pierwszej wersji - wyszedł przy uproszczeniu wyboru
kodowania, które przepuściło bajty bez znaczenia.

Zmienione oczekiwania istniejących testów: cztery testy sprawdzające zlecenie
zadania po zapisie wykonują teraz wywołania odłożone do zatwierdzenia
(`django_capture_on_commit_callbacks`), a test limitów kodowania używa
urwanego UTF-16 i bajtów bez znaczenia zamiast samego znacznika BOM.

## Co sprawdzić po wdrożeniu

1. Upload TXT zapisanego w Notatniku jako ANSI: polskie litery poprawne
   w podglądzie fragmentów.
2. Upload DOCX z cennikiem w tabeli: fragment zawiera usługę i cenę w jednej linii.
3. Upload dowolnego pliku: dokument dostaje fragmenty (zlecenie po zatwierdzeniu).
4. Rozmowa w widżecie w trakcie uploadu dużego pliku odpowiada bez opóźnienia.
