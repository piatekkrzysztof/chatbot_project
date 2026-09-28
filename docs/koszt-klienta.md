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

## Sufit kosztu: liczba do decyzji cenowej

Prompt jest przycinany do budżetu przed wysyłką (`OPENAI_MAX_INPUT_TOKENS`,
domyślnie 6000), a odpowiedź ograniczona przez `OPENAI_MAX_OUTPUT_TOKENS`
(600). Najdroższa możliwa wiadomość kosztuje więc:

```text
(6000 x 0,15 + 600 x 0,60) / 1 mln x 4,0 zł = 0,005 zł
```

Z tego wynika granica, której **żaden klient nie przekroczy, niezależnie od
wielkości swojej bazy wiedzy**:

| Plan | Cena | Sufit kosztu modelu | Udział w cenie |
|---|---|---|---|
| Start | 149 zł | 10 zł | **7%** |
| Grow | 349 zł | 40 zł | **12%** |
| Pro | 899 zł | 126 zł | **14%** |

To nie jest prognoza ani średnia, tylko konsekwencja limitów, które już są
w kodzie. Jeśli kiedyś przestaną wystarczać - bo podniesiemy budżet wejścia
albo zmienią się stawki OpenAI - te trzy liczby trzeba przeliczyć razem z nimi.

## Wynik z produkcji - 28.09.2026

Pierwszy pomiar **nową metodą** (2.14.0), z rozbiciem prosto od OpenAI:

| Pozycja | Wartość |
|---|---|
| Tokenów na wiadomość | 4 763 |
| Udział wyjścia | **1%** (wejście ~4 715, wyjście ~48) |
| Koszt wiadomości | 0,0029 zł |
| Start przy pełnym limicie | 5,85 zł z 149 zł (4%) |
| Grow | 23,39 zł z 349 zł (7%) |
| Pro | 73,10 zł z 899 zł (8%) |

Stawki 0,15 / 0,60 / 0,02 USD za milion, kurs 4,0, sprawdzone tego dnia na
[cenniku OpenAI](https://developers.openai.com/api/docs/pricing).

**Zastrzeżenie: to jedna wiadomość**, z czatu testowego panelu. Ruch z widgetu
może wyglądać inaczej. Pomiar warto powtórzyć, gdy uzbiera się kilkanaście
prawdziwych rozmów po wdrożeniu 2.14.0.

### Co ten pomiar zmienił w obrazie

Poprzedni pomiar, starą metodą, dawał 814 tokenów na wiadomość i 74% udziału
wyjścia. Obie liczby były nieprawdziwe, ale **w przeciwnych kierunkach**:

- udział wyjścia był zawyżony dwa rzędy wielkości (74% wobec 1%), bo metoda
  porównywała długość pytania z długością odpowiedzi;
- suma tokenów była zaniżona sześciokrotnie w stosunku do tego, co widać
  w czacie testowym - prompt z kontekstem jest znacznie dłuższy, niż wynikało
  ze średniej po starych wpisach.

Efekt netto: koszt wiadomości **wzrósł** z 0,0016 na 0,0029 zł, mimo że tańsza
okazała się ta część, która kosztuje najwięcej. Tańszy podział nie nadrobił
dłuższego promptu.

Wniosek dla cennika pozostaje ten sam co wczoraj, tylko teraz oparty na
pomiarze i na suficie, a nie na przedziale: marża jest zdrowa.

## Czego większy plan NIE daje

Dzisiejsza wiadomość zużyła **79% budżetu wejścia** przy bazie liczącej 320
fragmentów, czyli praktycznie pustej. Przy większej bazie `przytnij_do_budzetu`
zaczyna obcinać - najpierw najstarszą historię rozmowy, potem wiedzę od dołu
promptu systemowego (zasady zachowania i zakaz zmyślania zostają na górze).

Klient z planem Pro i bazą 50 MB **nie dostaje więcej kontekstu na odpowiedź**
niż klient z planem Start. Dostaje ten sam budżet 6000 tokenów, tylko lepiej
dobrany, bo jest z czego wybierać. Wartością większego planu jest trafniejszy
wybór fragmentów, a nie ich liczba w prompcie - i tak należy o tym mówić
w cenniku, żeby nie obiecać czegoś, czego produkt nie robi.
