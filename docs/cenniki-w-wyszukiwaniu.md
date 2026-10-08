# Cenniki, tabele i sekcje w wyszukiwaniu - 2.25.0 i 2.26.0

## Co wyszło przy odbiorze 7.10.2026

Właściciel wgrał na firmę Sm-art cennik w DOCX (osiem pozycji w tabeli)
i zapytał w widgecie „Ile kosztuje figurka z masy cukrowej?”. Bot odpowiedział
„nie posiadam informacji”, choć podgląd fragmentów (panel #44) pokazywał
wiersz „Figurka z masy cukrowej | 45 zł | …”.

`zmierz_prog_rag --firma 4` na produkcji: najbliższy był właściwy fragment,
ale **o 0,980 przy progu 0,96**. Cały cennik był jednym fragmentem, a wektor
fragmentu o ośmiu usługach jest uśrednieniem ośmiu tematów - pytanie o jedną
pozycję leży od niego daleko. Ten sam problem, przed którym chroni cięcie po
sekcjach ([F25](roadmapa-po-audycie.md)), tylko wewnątrz tabeli.

Wykluczone po drodze, prawdziwymi wywołaniami OpenAI:

- **model odmawia, bo cennik jest innej firmy niż agencja** - z tym samym
  promptem i opisem agencji gpt-4o-mini 3 razy na 3 odpowiedział „45 zł”;
- **wcześniejsza odmowa w historii rozmowy** - też 3 na 3 „45 zł”;
- **próg ustawiony inaczej na produkcji** - `RAG_MAX_DISTANCE=0.96`, jak w kodzie.

Do wektora wchodzi nazwa dokumentu razem z fragmentem (`tekst_do_wektora`).
Lokalny pomiar bez nazwy dawał 0,930 i maskował problem; z nazwą - 0,981,
zgodnie z produkcją.

## Co zmienia 2.25.0

**1. Wiersze tabel jako osobne fragmenty** (`documents/utils/fragmenty.py`).
Tabela z nagłówkiem i co najmniej dwoma wierszami danych - z DOCX
(„a | b | c”) albo z Markdowna („| a | b |”, bez linii `|---|`) - dostaje
dodatkowe fragmenty „nagłówek + wiersz”. Fragment całej tabeli zostaje,
więc pytanie o cały cennik działa jak dotąd. Nagłówek jest we fragmencie, bo
bez niego „Pakiet S | 99 zł | 199 zł” nie mówi, która cena jest netto.

**2. Dopasowanie po słowach** (`rag/engine.py`). Fragment, który zawiera
**wszystkie** słowa tematu pytania, trafia do wyników także za progiem,
o ile leży nie dalej niż 1,10. Słowa tematu to słowa od pięciu liter bez
pytających („kosztuje”, „macie”, „jakie”…), porównywane początkami, żeby
odmiana nie przeszkadzała („wypożyczacie” → „wypożyczenie”). Takie trafienia
dostają najwyżej dwa z pięciu miejsc; reszta to dotychczasowe wyniki
wektorowe. Warunek „wszystkie słowa” pilnuje ciszy: „serwis amortyzatorów
powietrznych” nie złapie fragmentu, w którym jest tylko „serwis”.

## Pomiar

Cennik z DOCX, zasady przechowywania (TXT) i oferta (TXT) przez prawdziwy
podział, prawdziwe embeddingi i prawdziwe wyszukiwanie, 8 pytań o rzeczy
z dokumentów i 6 spoza nich:

| Wariant | Trafione | Cisza |
|---|---:|---:|
| przed zmianą | 4 z 8 | 5 z 6 |
| tylko wiersze tabel | 6 z 8 | 5 z 6 |
| wiersze + słowa, granica 1,05 | 7 z 8 | 5 z 6 |
| **wiersze + słowa, granica 1,10 (2.25.0)** | **8 z 8** | **5 z 6** |

Jedyne pytanie bez ciszy - „Czy robicie torty w kształcie samochodu
wyścigowego?” - nie milknie też przed zmianą (fragment oferty o tortach leży
pod progiem). Wzorzec `ocen_rag` (zamrożone wektory, sklep rowerowy): trafność
90,9%, cisza 75,0% - **bez zmian** względem `main`.

## Koszt

Jedno dodatkowe zapytanie SQL na wiadomość (`ILIKE` po fragmentach firmy,
z odległością tylko dla pasujących). Dodatkowe fragmenty to dodatkowe
embeddingi przy wgraniu - grosze nawet przy dużym cenniku.

## Czego to nie robi

- Pytanie bez polskich znaków („zlocenia”) nie dopasuje się po słowach do
  „Złocenia” - wtedy zostaje samo wyszukiwanie wektorowe.
- Cennik zapisany zwykłym tekstem („Tort na chrzciny - od 320 zł”), bez
  tabeli, nie dostaje fragmentów na wiersz. Łapie go dopasowanie po słowach.

## Wdrożenie

Bez migracji i bez zmian w Renderze. **Istniejące dokumenty mają stare
fragmenty**, więc po wdrożeniu na produkcji (Render → Shell):

```sh
python manage.py przelicz_fragmenty
python manage.py przelicz_fragmenty --wykonaj
```

Pierwsze pokazuje na sucho, ile fragmentów będzie (dokumenty z tabelami
dostaną ich więcej), drugie przelicza. Przeliczenie liczy embeddingi
wszystkich dokumentów od nowa - przy obecnej bazie to ułamek złotówki.
Dopasowanie po słowach działa od razu po wdrożeniu, bez przeliczania.

Odbiór: na Sm-art pytania „Ile kosztuje figurka z masy cukrowej?”, „Macie
złocenia?”, „Jakie kwiaty jadalne macie?” - odpowiedzi z ceną albo treścią
z cennika.

**Odebrane na produkcji 8.10.2026.** 2.25.0 wdrożone, fragmenty przeliczone.
W Test bota wszystkie trzy pytania dostały odpowiedź z cennika, każda ze
źródłem `cennik-dekoracji-test1.docx`: „Figurka z masy cukrowej kosztuje
45 zł”, złocenia płatkowym złotem za 60 zł, kwiaty jadalne - bratki, róże
i chabry. Do 2.25.0 na pierwsze pytanie bot odpowiadał „nie posiadam
informacji”. Dokumenty testowe cukierni właściciel potem usunął z Sm-art.

## 2.26.0: sekcje w PDF i DOCX

### Co wyszło 8.10.2026

Test bota na trzystronicowej ofercie cateringu z PDF-a: 5 z 6 pytań dobrze,
ale „Co jeśli odwołam przyjęcie 10 dni wcześniej?” - odmowa. Przyczyna nie
w modelu ani w progu, tylko w podziale: **cały PDF dał trzy fragmenty, po
jednym na stronę**. Podział szukał granic sekcji po pustych liniach, a tekst
z PDF-a i DOCX-a ich nie ma - akapity są oddzielone pojedynczym znakiem nowej
linii. Fragment trzeciej strony mieszał anulowanie, płatność i kontakt
i leżał od pytania o 1,02 przy progu 0,96.

Ten sam błąd dotyczył każdego pliku, w którym treść zaczyna się w linii zaraz
pod nagłówkiem - także TXT. Dokument demo „Zakres serwisu i naprawy” dawał
jeden fragment zamiast pięciu sekcji.

Przy okazji: dopasowanie po słowach wymagało od fragmentu słów „jeśli”
i „wcześniej” - teraz są na liście słów pomocniczych.

### Co zmienia 2.26.0

Przed podziałem linia, która wygląda na nagłówek, dostaje puste linie wokół
siebie. Warunki, wszystkie naraz:

- krótka (do 80 znaków), bez kresek tabeli, wielka litera albo numer
  („3. Dowóz”);
- **poprzednia** linia kończy zdanie - odsiewa komórki tabel z PDF-a
  („Bufet Premium” po „przekąski”) i wiersze łamane w połowie zdania;
- **następna** zaczyna się wielką literą, cyfrą albo wypunktowaniem.

O tym, czy linia naprawdę zostanie nagłówkiem, nadal decyduje dotychczasowa
reguła (bez kropki, co najmniej 60 znaków treści pod spodem). Znaki sterujące
z ekstrakcji PDF-a (wypunktowanie odczytane jako ``) są usuwane - trafiały
do treści fragmentu i do podglądu w panelu.

### Pomiar

Pięć dokumentów (DOCX z tabelą, dwa TXT, dwa PDF), prawdziwy podział,
embeddingi i wyszukiwanie, 22 pytania o treść i 8 spoza niej:

| | Fragmentów | Trafione | Cisza |
|---|---:|---:|---:|
| 2.25.0 | 19 | 17 z 22 | 7 z 8 |
| **2.26.0** | 30 | **22 z 22** | **7 z 8** |

Naprawione: minimalna kwota z dowozem, zmiana smaku, reklamacja (regulamin
PDF), odwołanie i anulowanie przyjęcia (oferta PDF). Wzorzec `ocen_rag` bez
zmian (90,9% / 75,0%). Podział dokumentu o 2 mln znaków: 0,09 s.

### Uwaga o treści dokumentów

Z właściwym fragmentem w prompcie model 3 razy na 3 odpowiedział na pytanie
o odwołanie na 10 dni przed „zwrócimy całą zaliczkę”, a poprawnie jest
połowa. Winny był tekst testowy: „Anulowanie **do** 14 dni przed przyjęciem”
da się czytać na dwa sposoby. Bot czyta dokument dosłownie - niejednoznaczny
regulamin klienta da niejednoznaczną odpowiedź. Warto o tym mówić klientom
przy wdrożeniu.

### Wdrożenie

Bez migracji. Po wdrożeniu znowu przeliczenie, **najpierw na sucho**:

```sh
python manage.py przelicz_fragmenty
```

Dokumenty z PDF-a i DOCX-a dostaną więcej fragmentów. Jeśli przy jakiejś
firmie liczba skoczy nienaturalnie (np. kilkukrotnie przy stronach WWW),
zatrzymaj się i wklej wynik - to sygnał, że strona sprzedażowa ma linie,
które heurystyka bierze za nagłówki. Potem `--wykonaj`.
