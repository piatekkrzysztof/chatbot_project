# Pomiar lokalny - krok 1 testu obciążeniowego

Data: 16.09.2026. Wersja kodu: 2.8.0. Pierwszy krok z
[planu testu obciążeniowego](test-obciazeniowy.md): wariant lokalny, zero kosztów,
bez dotykania produkcji i bez wywołań modelu.

## Warunki

To jest pomiar **kształtu, nie przepustowości produkcyjnej**:

- laptop deweloperski, PostgreSQL 15.1 z pgvector 0.8 na tej samej maszynie,
- serwer deweloperski Django (`runserver`), jeden proces, **`DEBUG = True`** -
  na produkcji jest gunicorn z ośmioma wątkami i `DEBUG = False`,
- firma demonstracyjna na planie Grow (limit 150 zapytań/min), 4 dokumenty
  i 5 fragmentów - ekrany panelu i widgetu nie dotykają wyszukiwania wektorowego,
- scenariusz rozmowy pominięty: płaci tokenami za każde wywołanie.

Liczby bezwzględne z tej maszyny nie przenoszą się na Rendera. Przenosi się to,
gdzie coś puszcza i w jakim tempie rośnie.

## Wynik 1: wyszukiwanie wektorowe rośnie z liczbą fragmentów

`python manage.py zmierz_skale --do 85000 --wiem-ze-pisze-do-tej-bazy`

| fragmentów | mediana | najgorszy | plan, który tyle sprzedaje |
|---|---|---|---|
| 1 000 | 7,9 ms | 10,3 ms | |
| 5 000 | 16,5 ms | 20,5 ms | Start (5 MB ≈ 5 140) |
| 10 000 | 28,6 ms | 29,3 ms | |
| 25 000 | 70,2 ms | 79,5 ms | Grow (25 MB ≈ 25 700) |
| 40 000 | 110,7 ms | 113,0 ms | |
| 85 000 | 453,4 ms | 707,8 ms | powyżej Pro (50 MB ≈ 51 400) |

Do 40 tysięcy fragmentów czas rośnie liniowo (około 2,8 µs na fragment), potem
przyspiesza (5,3 µs) - w planie zapytania widać wtedy 29 796 bloków czytanych
z dysku zamiast z pamięci podręcznej.

Plan zapytania przy 85 tysiącach potwierdza, że **nie ma indeksu wektorowego**:

```
Limit -> Sort (top-N heapsort)
  -> Merge Join (dc.document_id = d.id)   rows=85000
     -> Index Scan documents_documentchunk_document_id
     -> Seq Scan documents_document  Filter: (uzywaj_w_wyszukiwaniu AND tenant_id = ...)
```

Każde pytanie liczy odległość dla **wszystkich** fragmentów firmy, a filtr firmy
siedzi na złączonej tabeli dokumentów, nie na fragmencie.

## Wynik 2: limit planu chroni aplikację wcześniej, niż ta się zmęczy

`python manage.py zmierz_obciazenie --rps N --czas 20` (nowa komenda, biblioteka
standardowa, bez scenariuszy płatnych):

| żądań/s | widget (p95) | panel (p95) | odpowiedzi 429 | 5xx |
|---|---|---|---|---|
| 4 | 101-107 ms | 97-125 ms | brak | brak |
| 8 | 98-107 ms | 110-120 ms | 19 z 40 na FAQ | brak |
| 16 | 101-107 ms | 106-113 ms | 167 z 224 na widgecie | brak |
| 32 | 73-79 ms | 90-114 ms | 437 z 448 na widgecie | brak |

Wszystkie progi SLO dotrzymane na każdym poziomie, ale **nie dlatego, że system
jest niewyczerpalny**: powyżej 2,5 żądania na sekundę (limit planu Grow) ruch
widgetu jest odrzucany kodem 429, a odrzucenie jest tanie. Panel ma limit
dziesięciokrotnie wyższy i przy 32 żądaniach na sekundę nadal odpowiada w ~100 ms.

**Wniosek dla projektu testu:** jedno konto nie jest w stanie wysycić instancji,
bo wcześniej trafi we własny limit. Żeby zmierzyć pojemność, ruch musi pochodzić
z **wielu firm naraz** (wiele kluczy) - inaczej mierzy się throttling, a nie system.
To zmienia scenariusz produkcyjny z planu.

## Ustalenia do rozstrzygnięcia

1. **Liczby w `accounts/plans.py` nie zgadzają się z tym pomiarem.** W kodzie stoi
   0,19 s przy 5 tysiącach fragmentów i 1,04 s przy 25 tysiącach; dziś wychodzi
   16,5 ms i 70,2 ms, czyli 10-15 razy szybciej. Chronologia wyklucza najprostsze
   wyjaśnienie: wektor skrócono do 512 wymiarów 7 września, a tamte liczby wpisano
   8 września, już po zmianie. Komenda pomiarowa od tego czasu się nie zmieniła.
   **Nie zmieniam na tej podstawie limitów planów** - to na tych liczbach oparto
   obcięcie Pro ze 100 MB do 50 MB. Rozstrzygnie pomiar na produkcji:
   `zmierz_skale` w domyślnym rozmiarze (10 tysięcy fragmentów, około 27 MB).
2. **Rozmiar fragmentu też się rozjechał:** 0,8 kB zmierzone wobec 2,8 kB zapisanych
   w kodzie. Wbudowana kontrola w `zmierz_skale` sama to zgłosiła - przyrząd działa
   tak, jak zaprojektowano, i to on wykrył własny rozjazd.
3. **Indeks wektorowy nie jest dziś pilny.** Przy pełnym planie Pro (51 400
   fragmentów) wyszukiwanie mieści się w ~150-250 ms na tej maszynie, wobec
   trzysekundowego progu na pierwszy fragment odpowiedzi, w którym i tak dominuje
   czas modelu. Decyzja po powtórzeniu pomiaru na produkcji.
4. Gdyby indeks był potrzebny, to **nie jest jedna migracja**: filtr firmy siedzi
   na złączonej tabeli, więc indeks ANN wymagałby przeniesienia `tenant_id`
   i flagi „używaj w wyszukiwaniu" na fragment, migracji danych i sprawdzenia
   jakości odpowiedzi (`ocen_rag`).

## Czego ten pomiar nie mówi

- Ile wytrzyma instancja na Renderze: inny procesor, gunicorn z ośmioma wątkami,
  `DEBUG = False`, sieć między usługami.
- Jak zachowa się czat: scenariusz rozmowy wymaga zgody na koszt tokenów.
- Co się stanie przy wielu firmach naraz - i to jest teraz najważniejsze pytanie.

## Następny krok

`zmierz_skale` w domyślnym rozmiarze na produkcji (27 MB, dane kasowane na końcu)
rozstrzygnie punkt 1 i powie, czy limity planów opisują rzeczywistość. Dopiero
potem ma sens decyzja o indeksie i o pełnym teście z wieloma firmami.
