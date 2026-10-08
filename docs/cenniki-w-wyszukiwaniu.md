# Cenniki i tabele w wyszukiwaniu - 2.25.0

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
