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

## Część 2 (osobny PR)

Z przeglądu kodu przy tej części, jeszcze nieodtworzone testami:

- **Limit bazy wiedzy przy równoległych dodaniach.** Sprawdzenie i zapis nie
  są objęte blokadą, więc dwa uploady naraz mogą razem przekroczyć limit planu.
  Zadania w tle zlecane są przed zatwierdzeniem transakcji.
- **TXT i MD wyłącznie w UTF-8.** Plik zapisany w Windows-1250 albo UTF-16 jest
  odrzucany.
- **Tabele DOCX** tracą układ wierszy: usługa i jej cena trafiają do osobnych
  linii, a podział na fragmenty może je rozdzielić.
