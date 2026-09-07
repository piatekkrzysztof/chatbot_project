"""
Ile liczb ma jeden wektor.

Dlaczego to jest stała w kodzie, a nie zmienna środowiskowa
-----------------------------------------------------------
Szerokość kolumny `documents_documentchunk.embedding` jest wpisana w migrację.
Postgres nie przyjmie do kolumny `vector(512)` wektora o innej długości i nie
da się tego zmienić przez restart z inną zmienną. Ustawienie w środowisku
sugerowałoby, że da się - i pierwsza osoba, która by je przestawiła, dostałaby
błąd przy każdym zapisie fragmentu, nie zmieniony wymiar.

Zmiana tej liczby to zmiana schematu bazy PLUS przeliczenie wszystkich
wektorów od nowa. Jak to zrobić: docs/zmiana-wymiaru-wektora.md.

Dlaczego 512, a nie 1536
------------------------
`text-embedding-3-small` domyślnie oddaje 1536 liczb, ale przyjmuje parametr
`dimensions` i jest trenowany tak, żeby krótszy wektor tracił jakość łagodnie,
zamiast się rozsypywać. 512 liczb to nie „pierwsza jedna trzecia" długiego
wektora - to wektor, który model policzył z myślą o tej długości.

Zmierzone przed migracją (docs/skala-i-wydajnosc.md):

    jakość   trafność 90,9%, cisza 75,0% - tyle samo, co przy 1536,
             po przesunięciu RAG_MAX_DISTANCE z 1,00 na 0,98
    rozmiar  2,9 razy mniej miejsca w bazie
    czas     1,6 raza szybsze liczenie odległości

Rozmiar był ważniejszy od czasu. Produkcja przy 10 000 fragmentów czytała
z dysku około 79 MB na każde pytanie, bo tabela nie mieściła się w pamięci
instancji. Te same fragmenty przy 512 wymiarach to 27 MB.
"""

#: Liczba wymiarów wektora. Musi się zgadzać z:
#:   - kolumną `embedding` w documents/models.py,
#:   - parametrem `dimensions` w każdym wywołaniu API embeddingów,
#:   - polem "wymiarow" w rag/ocena/wzorzec.json.
#: Pilnuje tego documents/tests/test_wymiar.py.
WYMIAR_WEKTORA = 512
