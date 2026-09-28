# Koszt krańcowy klienta

Stan na 28.09.2026, wersja 2.14.0. Odpowiedź na pytanie, którego dotąd nikt nie
zadał liczbami: **ile kosztuje nas klient, który wykorzysta to, za co zapłacił.**

## Po co

Cennik obiecuje 2 000, 8 000 i 25 000 wiadomości miesięcznie za 149, 349 i 899
złotych. Dopóki nie wiadomo, ile kosztuje jedna wiadomość, te trzy liczby są
zgadywaniem, które wygląda na decyzję. Przy pierwszym kliencie Pro, który
naprawdę wyśle 25 000 wiadomości, zgadywanie zamienia się w rachunek.

```bash
python manage.py zmierz_koszt_klienta
```

Komenda czyta logi zużycia, liczy koszt jednej wiadomości i pokazuje, co z ceny
każdego planu zostaje przy pełnym wykorzystaniu limitu. Niczego nie wywołuje
i nie zmienia.

## Jak pomiar dzieli tokeny

Od 2.14.0 zapisujemy `prompt_tokens` i `completion_tokens` osobno, wprost
z odpowiedzi OpenAI. Dla wpisów po tej zmianie nie ma tu czego szacować,
a wypis mówi „POMIAR".

**Dlaczego to było potrzebne.** Do 2.13.0 log miał wyłącznie sumę, więc podział
odtwarzaliśmy z długości promptu i odpowiedzi. Pierwsze uruchomienie na
produkcji pokazało 74% udziału wyjścia - liczbę niemożliwą przy RAG-u, gdzie
wejście niesie kontekst z bazy wiedzy. Przyczyna: `PromptLog.prompt` zapisuje
**pytanie odwiedzającego**, a nie prompt wysłany do modelu. Kontekstu z bazy
wiedzy nie ma w logu w ogóle, więc porównanie mierzyło długość pytania wobec
długości odpowiedzi, czyli nic z tego, co miało mierzyć.

Ponieważ wyjście kosztuje czterokrotnie drożej, stary sposób **zawyżał** koszt.
Wpisy sprzed 2.14.0 dalej liczą się po staremu i wypis podaje, ile ich jest -
dla nich wynik należy czytać jako górne ograniczenie, nie jako pomiar.

## Ceny podaje się z linii poleceń

Stawki OpenAI i kurs dolara zmieniają się częściej niż ten kod. Wpisana na stałe
cena po cichu dezaktualizuje wynik, a nikt nie zauważy, bo liczba nadal wygląda
wiarygodnie.

```bash
python manage.py zmierz_koszt_klienta --usd-wejscie 0.15 --usd-wyjscie 0.60 \
  --usd-embedding 0.02 --kurs 4.0 --dni 30
```

Domyślne wartości pochodzą z cennika `gpt-4o-mini` i `text-embedding-3-small`
z września 2026. **Sprawdź je przed użyciem wyniku do decyzji.**

## Co wchodzi w koszt krańcowy

| Składnik | Jak liczony |
|---|---|
| Tokeny wejściowe modelu | prompt razem z kontekstem z bazy wiedzy |
| Tokeny wyjściowe modelu | odpowiedź, stawka kilkukrotnie wyższa |
| Wektor pytania | jeden embedding na każde pytanie odwiedzającego |
| Wektory bazy wiedzy | jednorazowo, przy wgraniu materiałów - pokazywane osobno |

**Nie wchodzi:** hosting (stały, niezależny od liczby klientów), poczta, prowizja
Stripe i czas pracy. To jest koszt krańcowy - ten, który rośnie z każdym nowym
klientem - a nie pełny koszt usługi.

## Jak czytać wynik

Marża liczona jest dla **pełnego wykorzystania limitu**, nie dla średniej.
Klient płacący za 25 000 wiadomości i wysyłający 300 jest zyskowny zawsze;
pytanie brzmi, czy pozostaje zyskowny ten, który bierze to, za co zapłacił.

Jeśli udział kosztu modelu w cenie planu wyjdzie:

- **poniżej 10%** - cennik ma zapas, marża jest zdrowa;
- **10-30%** - warto obserwować, zwłaszcza przy zmianie stawek OpenAI albo kursu;
- **powyżej 30%** - plan wymaga przeliczenia, bo jeden klient wykorzystujący
  limit zjada większość tego, co za niego płaci.

Największy wpływ na wynik ma **długość promptu**, czyli ile kontekstu z bazy
wiedzy wysyłamy przy każdym pytaniu - nie sam rozmiar bazy. Klient z dużą bazą
kosztuje więcej nie dlatego, że trzyma dużo, tylko dlatego, że do każdego
pytania dokładamy więcej fragmentów.

## Wynik z produkcji - 28.09.2026

Pierwszy pomiar, jeszcze **starą metodą** (przed 2.14.0), na 24 wiadomościach
z 30 dni. Traktować jako górne ograniczenie:

| Pozycja | Wartość |
|---|---|
| Tokenów na wiadomość | 814 |
| Udział wyjścia (zawyżony, patrz wyżej) | 74% |
| Koszt wiadomości | 0,0016 zł |
| Start: koszt modelu przy pełnym limicie | 3,11 zł z 149 zł (**2%**) |
| Grow | 12,45 zł z 349 zł (**4%**) |
| Pro | 38,90 zł z 899 zł (**4%**) |

Stawki: 0,15 / 0,60 / 0,02 USD za milion, kurs 3,95. Ceny sprawdzone tego dnia
na [cenniku OpenAI](https://developers.openai.com/api/docs/pricing).

**Wniosek jest odporny na błąd metody.** Nawet gdyby wszystkie 814 tokenów było
wyjściem - przypadek najdroższy z możliwych - Pro kosztowałby 48 zł z 899, czyli
5%. Gdyby wszystko było wejściem: 12 zł, czyli 1%. Cały przedział mieści się
w paśmie „zdrowa marża", więc decyzji cenowej nie zmienia.

**Czego ta liczba nie mówi.** Zmierzono ją na bazie wiedzy praktycznie pustej
(320 fragmentów). Koszt rośnie z długością promptu, czyli z liczbą fragmentów
dokładanych do każdego pytania - klient z wypełnionym planem Pro wyśle
kilkukrotnie dłuższe wejście. Pomiar warto powtórzyć, gdy taki klient się
pojawi; wtedy będzie już liczony nową metodą, bez szacowania.
