# F17 — atomowa i powtarzalna publikacja fragmentów

**Zakres:** `documents/utils/embedding_generator.py`,
`documents/tasks.py` (zadanie `generate_embeddings_for_document`),
`documents/management/commands/przelicz_fragmenty.py`.

**Nie zmienia:** schematu bazy (bez migracji), zmiennych środowiskowych, usług,
panelu, widgetu ani sposobu podziału tekstu na fragmenty.

**Wdrożenie:** web i worker z tym samym commitem. Generator wołają oba procesy
(upload przez sygnał po zapisie, odświeżanie stron w workerze, ręczne
przeliczenie z powłoki), a opcje zadania czyta worker.

---

## Dlaczego to ważne

Fragmenty są danymi pochodnymi treści dokumentu, ale bot widzi **wyłącznie
fragmenty**. Każdy stan, w którym rozjeżdżają się z treścią, to stan, w którym
bot nie zna dokumentu albo zna jego wersję, której już nie ma — a panel pokazuje
przy tym status „gotowe".

## Co było zepsute

Publikacja kasowała stare fragmenty i zapisywała nowe dwoma osobnymi
poleceniami, poza transakcją, w tej kolejności. Wynikały z tego cztery ciche
awarie:

| # | Sytuacja | Skutek |
|---|---|---|
| 1 | Przerwanie między kasowaniem a zapisem — restart workera, błąd bazy, wdrożenie | Dokument z **zerem fragmentów** przy `processed=True` |
| 2 | Model zwraca mniej wektorów niż fragmentów | `zip(strict=True)` pada **po** skasowaniu — ten sam skutek |
| 3 | Dwa zadania dla jednego dokumentu (odświeżenie strony w trakcie poprzedniego przeliczenia) | Publikacja w kolejności **zakończenia**, nie treści: starsze zadanie nadpisuje nowsze fragmenty nieaktualnymi, na stałe |
| 4 | Nowa treść dzieli się na zero fragmentów | Funkcja kończyła się przed kasowaniem — zostawały fragmenty **poprzedniej** treści |

Do tego dwie rzeczy po stronie zadania w tle:

- Celery domyślnie potwierdza zadanie przy odebraniu, więc worker zabity
  w trakcie liczenia **gubił je bez śladu**.
- Awaria liczenia wektorów zostawała wyłącznie w logu workera. Panel pokazywał
  dokument jako przetworzony.

## Jak jest teraz

1. **Migawka z bazy.** Treść i nazwę bierzemy z wiersza w bazie, nie z obiektu
   podanego przez wywołującego. To, co zapisane, jest tym, co publikujemy.
2. **Wektory poza transakcją.** Wywołanie API trwa sekundy i nie może trzymać
   blokady wiersza przez ten czas.
3. **Publikacja w jednej transakcji** pod `select_for_update` wiersza dokumentu.
   Skasowanie i zapis są dla wyszukiwania widoczne naraz albo wcale.
4. **Kontrola aktualności pod blokadą.** Jeśli treść albo nazwa różnią się od
   migawki, nie publikujemy. Nowszą wersję publikuje zadanie zlecone przy jej
   zapisie (import strony i upload zlecają je zawsze po zmianie treści).
5. **Kontrola liczby wektorów przed transakcją.** Niezgodność przerywa
   przeliczenie, zanim cokolwiek zniknie.
6. **Pusty podział publikuje pusty zbiór** — fragmenty poprzedniej treści
   znikają.

Zadanie w tle:

- `acks_late=True`, `reject_on_worker_lost=True` — zadanie przerwane utratą
  workera wraca do kolejki. To jest bezpieczne dzięki powtarzalności poniżej.
- Awaria zapisuje przy dokumencie komunikat `BLAD_WEKTOROW` (status w panelu:
  `failed`) — **tylko wtedy, gdy pole `processing_error` jest puste**. Błąd
  wyodrębniania tekstu jest ważniejszy i nie może zniknąć pod komunikatem
  o wektorach.
- Udana publikacja czyści **wyłącznie** `BLAD_WEKTOROW`. Udane przeliczenie
  starej treści nie znaczy, że nowy plik dał się przeczytać.
- Dokument skasowany, zanim zadanie ruszyło, kończy zadanie bez błędu.

## Powtarzalność

Jeśli opublikowane fragmenty mają dokładnie te treści, które daje podział
obecnej treści, generator **nie woła API**. Zadanie zlecone dwukrotnie albo
ponowione po utracie workera kosztuje wtedy zero. To samo sprawdzenie
powtarzamy pod blokadą, bo równoległe zadanie mogło w międzyczasie opublikować
dokładnie to samo.

`przelicz_fragmenty --wykonaj` przelicza **z wymuszeniem**. Ta komenda istnieje
po to, żeby przeliczyć mimo braku zmian w treści — po zmianie modelu embeddingów
albo wymiaru wektora treści fragmentów są identyczne, a wektory trzeba policzyć
od nowa.

## Świadome ograniczenia

- **Sama zmiana nazwy dokumentu** nie wywoła przeliczenia. Nazwa wchodzi do
  wektora, ale porównujemy treść fragmentów. Nie wywoływała go też wcześniej:
  nic nie zleca zadania po zmianie nazwy.
- **Pusta treść w zadaniu w tle nie kasuje fragmentów.** Pusta treść bierze się
  dziś głównie z pobrania strony, które nic nie zwróciło; skasowanie wiedzy po
  jednym nieudanym pobraniu byłoby gorsze od odpowiadania z poprzedniej wersji
  do następnego odświeżenia. Właściwa poprawka należy do importu (**F10**):
  pusta strona nie powinna nadpisywać treści. Wywołanie generatora wprost
  (np. z `przelicz_fragmenty`) pustą treść publikuje jako pusty zbiór.
- **Edycja treści w panelu administracyjnym Django** nie zleca przeliczenia —
  sygnał po zapisie robi to tylko dla dokumentu bez fragmentów. To dostęp
  wyłącznie dla obsługi, stan sprzed tej zmiany.

## Weryfikacja

Nowy plik `documents/tests/test_atomowa_publikacja.py`, 15 przypadków.

**Odtworzenie błędu:** na kodzie sprzed zmiany czerwienieje 12 z nich, a przypadek
dokumentu skasowanego w trakcie liczenia kończy się dodatkowo błędem klucza
obcego przy zapisie fragmentów. Trzy przechodzą także na starym kodzie i to jest
zamierzone: pilnują, żeby nowy kod nie zasłaniał błędu wyodrębniania tekstu
i nie czyścił go przy udanym przeliczeniu — stary kod nie zapisywał niczego, więc
nie miał czego zasłonić.

**Weryfikacja mutacyjna** (13.09.2026): każde z siedmiu celowych uszkodzeń
nowego kodu czerwieni co najmniej jeden test - usunięcie kontroli aktualności,
pominięcia przed API i transakcji; czyszczenie każdego błędu zamiast tylko
`BLAD_WEKTOROW`; `acks_late=False`; nadpisanie błędu wyodrębniania; ignorowanie
`wymus`. Nie mutowaliśmy powtórnego sprawdzenia pominięcia pod blokadą: chroni
wyłącznie przed zbędnym zapisem tych samych fragmentów, więc jego brak nie daje
złego wyniku, tylko dodatkowe polecenie w bazie.

Testy używają PostgreSQL (`select_for_update` bez PostgreSQL niczego nie
blokuje). Równoległość jest odtwarzana deterministycznie: udawany model w trakcie
„liczenia" starszego zadania zmienia treść i uruchamia nowsze zadanie do końca.

## Co sprawdzić po wdrożeniu

1. `python manage.py przelicz_fragmenty --firma NUMER` (na sucho) — liczby
   fragmentów bez zmian względem stanu sprzed wdrożenia.
2. Na wydzielonej firmie: odświeżenie źródła WWW dwa razy pod rząd bez zmian na
   stronie — w logu brak wywołań API embeddingów przy drugim przebiegu.
3. Pulpit → „Wiedza, którą zna bot": brak nowych dokumentów „bez fragmentów".

## Związek z pozostałymi ustaleniami etapu 5

- **F18** (usuwanie plików i pochodnych): skasowanie dokumentu nadal nie usuwa
  pliku z magazynu. To automatyczne usuwanie danych, a roadmapa odkłada
  włączanie takich operacji do odbioru pełnego odtworzenia z kopii.
- **F10** (import): pusta strona nadpisująca treść — patrz ograniczenia wyżej.
