# Koszt krańcowy klienta

Stan na 17.09.2026, wersja 2.13.0. Odpowiedź na pytanie, którego dotąd nikt nie
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

## Czego ten pomiar nie wie dokładnie

**Logi zapisują sumę tokenów, nie rozbicie.** `usage.total_tokens` to wejście
i wyjście razem, a OpenAI liczy je osobno i po różnych stawkach - wyjście zwykle
kilkukrotnie drożej. Z jednej liczby nie da się odtworzyć rachunku.

Podział szacujemy z długości tekstów, które w logu są: promptu i odpowiedzi.
To przybliżenie - tokenizacja nie jest wprost proporcjonalna do znaków, a polski
tekst ma inny stosunek znaków do tokenów niż angielski. Przy stawkach
różniących się czterokrotnie błąd podziału o kilka punktów procentowych zmienia
wynik o kilka procent, nie o rząd wielkości: **do decyzji cenowej wystarczy, do
faktury nie.**

Właściwe rozwiązanie to zapisywanie `prompt_tokens` i `completion_tokens`
osobno. OpenAI zwraca oba w tej samej odpowiedzi, z której bierzemy dziś sumę,
więc to kilka linii w `api/utils/chat_engine.py` plus migracja. Do czasu tej
zmiany wynik jest oznaczony jako szacunek i tak należy go czytać.

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

## Wynik pomiaru

Do wypełnienia po uruchomieniu na produkcji. Pomiar z bazy deweloperskiej nie
nadaje się na nic: prompty pochodzą z testów i są kilkanaście razy krótsze niż
prawdziwe.
