# Test obciążeniowy - plan do zatwierdzenia (etap 8)

Stan na 16.09.2026, wersja 2.8.0. Ostatni punkt [odbioru komercyjnego](roadmapa-po-audycie.md),
którego nie da się zrobić samym kodem: wymaga decyzji właściciela o środowisku,
narzędziu i koszcie. **Ten dokument niczego nie uruchamia.**

## Wykonanie - decyzja z 11.10.2026

Właściciel wybrał **mały profil na produkcji**: poza godzinami pracy, na koncie
testowym, z limitem 20 zł na model. Narzędzie:
[`narzedzia/test_obciazenia/test_obciazenia.py`](../narzedzia/test_obciazenia/test_obciazenia.py)
zamiast k6 - Python i `httpx` z istniejącego środowiska backendu, bez pobierania
nowych programów; progi te same co niżej.

Domyślny profil (10 minut) mieści się w limitach planu próbnego, więc każde 429
jest wynikiem do wyjaśnienia: odczyty widgetu 0,8/s (limit 60/min na firmę),
panel 2/s, eksport CSV raz na ok. pół minuty, 15 rozmów strumieniem (limit
odwiedzającego 20 na godzinę z jednego adresu). Kontakt (scenariusz 3) pominięty -
wysyłałby maile i ma limit 5 na adres. Koszt modelu: ok. 0,0005 zł na wiadomość
([wybór modelu](wybor-modelu.md)), czyli grosze - limit 20 zł nie jest bliski.

```sh
python narzedzia/test_obciazenia/test_obciazenia.py --backend https://api.agencjasm-art.pl \
    --panel https://panel.agencjasm-art.pl --klucz KLUCZ_WIDGETU --strona https://cdpn.io
```

Sprawdzone lokalnie 12.10.2026 na krótkim przebiegu (widget, panel, eksport,
rozmowy strumieniem).

### Wynik produkcji 12.10.2026, 11:03-11:13 (2.32.0) - przed poprawką

| Ruch | Żądań | p50 | p95 | maks | Próg p95 |
|---|---|---|---|---|---|
| Widget | 481 | 756 ms | 2200 ms | 3402 ms | 500 ms - **przekroczony** |
| Panel | 1181 | 798 ms | 2202 ms | 4109 ms | 800 ms - **przekroczony** |
| Czat: pierwsze słowa | 15 | 3,6 s | 5,2 s | 5,9 s | 3 s - **przekroczony** |
| Czat: cała odpowiedź | 15 | 3,9 s | 5,6 s | 6,3 s | - |
| Eksport CSV | 20 | 435 ms | 1350 ms | 1516 ms | - |

Zero błędów 5xx i zero odmów 429 przy 1697 żądaniach. Zapis:
[test-obciazenia-2026-10-12-przed.json](test-obciazenia-2026-10-12-przed.json).

**Przyczyna:** pojedyncze `/health/` bez obciążenia trwało 0,4-2,4 s, a odrzucone
od razu żądanie ~90 ms (sieć i Cloudflare w porządku). Pomiar w powłoce
produkcji: `CONN_MAX_AGE=0` i baza podłączona **adresem zewnętrznym** - nowe
połączenie z bazą 330-740 ms przy każdym żądaniu, zapytanie na otwartym
połączeniu 2 ms, Redis 5 ms. Poprawka: utrzymywanie połączeń (2.32.1)
i wewnętrzny adres bazy w `DATABASE_URL` (właściciel, w Renderze).

### Wynik produkcji 12.10.2026, 17:25-17:35 (2.32.1) - po poprawce

Ten sam profil i to samo konto testowe. W powłoce produkcji przed testem:
`CONN_MAX_AGE=60`, baza adresem wewnętrznym, nowe połączenie 105-200 ms
(płacone raz na proces co najwyżej co 60 s, a nie przy każdym żądaniu).

| Ruch | Żądań | p50 | p95 | maks | Próg p95 | Przed (p95) |
|---|---|---|---|---|---|---|
| Widget | 481 | 69 ms | 165 ms | 385 ms | 500 ms - OK | 2200 ms |
| Panel | 1181 | 73 ms | 205 ms | 1045 ms | 800 ms - OK | 2202 ms |
| Czat: pierwsze słowa | 15 | 2,0 s | 3,3 s | 4,8 s | 3 s - **przekroczony** | 5,2 s |
| Czat: cała odpowiedź | 15 | 2,4 s | 3,6 s | 5,0 s | - | 5,6 s |
| Eksport CSV | 20 | 87 ms | 156 ms | 160 ms | - | 1350 ms |

Zero błędów 5xx i zero odmów 429 przy 1697 żądaniach. Zapis:
[test-obciazenia-2026-10-12-po.json](test-obciazenia-2026-10-12-po.json).

**Panel i widget mieszczą się w progach z dużym zapasem** - p95 ok. 10 razy
niżej niż przed poprawką. Brak żądań panelu > 3 s.

**Czat przekracza próg nieznacznie** (p95 3,3 s przy celu 3 s). Przy 15
rozmowach p95 wyznacza praktycznie jedna-dwie najwolniejsze odpowiedzi
(maks 4,8 s), więc to wynik orientacyjny. Mediana 2,0 s. Lokalnie sam model
(gpt-6-luna, `medium`) dawał 1,1 / 2,6 s ([wybór modelu](wybor-modelu.md));
reszta to wyszukiwanie wiedzy (wektor pytania z API OpenAI, zapytania do bazy)
i sieć. Dalsze kroki - decyzja właściciela: `OPENAI_REASONING_EFFORT=low`
(lokalnie 0,8 / 1,5 s, ale 1 błąd rachunkowy na 18 prób) albo najpierw pomiar
etapów przed pierwszym słowem i poprawka bez zmiany jakości.

## Po co

[SLO](slo-i-czasy-odpowiedzi.md) mówi, jak szybko ma odpowiadać system, ale nie
mówi, **przy ilu jednoczesnych rozmowach** te progi jeszcze się trzymają. Bez
tej liczby nie da się odpowiedzieć na pytanie klienta „czy wytrzyma nasz ruch"
ani zaplanować, kiedy dokładać zasoby. Dziś jedyna odpowiedź to „nie wiemy".

## Co uznajemy za zaliczone

Progi wprost z SLO, mierzone przy zadanym obciążeniu:

| Obszar | Próg |
|---|---|
| Ekrany i listy panelu | p95 < 800 ms, brak żądań > 3 s |
| Widget: ustawienia, FAQ, kontakt | p95 < 500 ms |
| Widget: pierwszy fragment odpowiedzi czatu | p95 < 3 s |
| Błędy 5xx | < 0,5% żądań |
| Odrzucenia 429 | tylko tam, gdzie wynikają z limitu planu - każde inne to błąd testu |

Wynikiem testu jest **liczba jednoczesnych rozmów i żądań na sekundę, przy
których progi jeszcze się trzymają** - a nie „przeszło/nie przeszło".

## Narzędzie

| Narzędzie | Za | Przeciw |
|---|---|---|
| **k6** (rekomendowane) | Jeden plik wykonywalny, bez zależności w projekcie; progi (`thresholds`) w samym skrypcie, więc test sam odpowiada „zaliczone/nie"; scenariusze w JavaScripcie, czytelne dla panelu i widgetu | Trzeba pobrać binarium na maszynę, z której lecimy |
| Locust | Python, czyli język backendu; łatwo użyć istniejących fikstur i klienta HTTP | Nowa zależność deweloperska w projekcie; progi trzeba dopisać ręcznie |
| `ab`, `hey`, `oha` | Nic do instalowania poza jednym plikiem | Brak scenariuszy wielokrokowych (logowanie, token, strumień) - nie zmierzą tego, co nas interesuje |

**Rekomendacja:** k6. Nie dodaje niczego do repozytorium ani do obrazu produkcyjnego,
a scenariusz z progami zostaje w `docs/` jako dowód z odbioru.

## Środowisko - trzy warianty

| Wariant | Co naprawdę mierzy | Koszt | Ryzyko |
|---|---|---|---|
| **A. Lokalnie** (backend na maszynie, PostgreSQL lokalnie) | Zachowanie kodu: liczba zapytań, wyszukiwanie wektorowe, limity. **Nie mierzy** Rendera, sieci ani dysku | Zero | Żadne dla klientów |
| **B. Efemeryczny staging na Renderze** (usługa web + baza, skasowana po teście) | To samo, co produkcja, bez ryzyka dla klientów | Nowa instancja i baza na kilka godzin - **poza obecnym budżetem, wymaga Twojej decyzji** | Żadne dla klientów |
| **C. Produkcja poza godzinami pracy** | Prawdę o produkcji | Zero dodatkowego hostingu, ale realne tokeny OpenAI | Klient trafiający w to okno zobaczy wolniejsze odpowiedzi; limit wiadomości konta testowego zostanie zużyty |

**Rekomendacja:** A najpierw (szukamy wąskiego gardła w kodzie, za darmo), potem
C na małym profilu i poza godzinami pracy - wyłącznie na koncie testowym. B tylko
wtedy, gdy zdecydujesz o koszcie: to jedyny wariant, który mierzy produkcję bez
dotykania klientów.

## Scenariusze

Ruch odwzorowuje realny rozkład: większość żądań widgetu to odczyty, rozmowy są
rzadsze, panel to pojedyncze osoby.

| # | Scenariusz | Ścieżka | Udział | Uwagi |
|---|---|---|---|---|
| 1 | Odwiedzający otwiera widget | `GET /api/widget-settings/`, `GET /api/widget/faq/` | 60% | Sam odczyt, bez kosztów modelu |
| 2 | Rozmowa z botem | `POST /api/widget/chat/stream/` | 15% | **Płatne**: tokeny OpenAI. Mierzymy czas do pierwszego fragmentu |
| 3 | Zostawienie kontaktu | `POST /api/widget/contact/` | 5% | Zapis do bazy, e-mail idzie przez zadanie w tle |
| 4 | Panel: pulpit i listy | `GET /api/analytics/`, `/api/chat/logs/?page=1`, `/api/documents/?page=1` | 15% | Z tokenem JWT; sprawdza też stałą liczbę zapytań pod obciążeniem |
| 5 | Eksport historii | `GET /api/chat/export/` | 5% | Odpowiedź strumieniowa; osobno, bo długa i rzadka |

Poza zakresem: webhook Stripe (wymaga prawdziwego podpisu i tworzyłby zdarzenia
płatności), rejestracja i logowanie (limity IP z definicji odrzucą sztuczny ruch),
wgrywanie dokumentów (mierzone osobno przy limicie bazy wiedzy).

## Profil obciążenia i sufit limitów

Limity planów są **częścią systemu**, a nie przeszkodą w teście: powyżej nich
backend ma odpowiadać 429 i to jest poprawne zachowanie.

| Plan konta testowego | Limit | Sufit ruchu bez 429 |
|---|---|---|
| Start | 60 zapytań/min | 1 zapytanie/s |
| Grow | 150/min | 2,5/s |
| **Pro** | 500/min | **8,3/s** |

Profil: rozgrzewka 1 minuta, następnie stopniowo 1 → 8 żądań na sekundę przez
10 minut, na koncie z planem Pro. Powyżej 8,3/s mierzymy już limit, nie system.
Gdybyśmy chcieli zmierzyć system powyżej tej granicy, trzeba **świadomie i na
czas testu** podnieść limit konta testowego - i zapisać to w raporcie, bo wynik
przestaje wtedy odpowiadać zachowaniu produkcyjnemu.

## Koszt

Scenariusz 2 to jedyny płatny element: każde pytanie to wektor pytania plus
odpowiedź modelu. Ograniczenia z ustawień: `OPENAI_MAX_INPUT_TOKENS` 6000,
`OPENAI_MAX_OUTPUT_TOKENS` 600, model `gpt-4o-mini`.

Przy profilu wyżej (10 minut, 15% z ~8/s) wychodzi około **700 rozmów**, czyli
maksymalnie ~4,2 mln tokenów wejściowych i ~420 tys. wyjściowych. Przed
uruchomieniem policz to po aktualnym cenniku OpenAI - **nie uruchamiam scenariusza
2 bez Twojej zgody na ten koszt**, tak samo jak przy płatnościach.

Wariant tańszy, gdy koszt ma być bliski zeru: uruchomić scenariusze 1, 3, 4 i 5
w pełnym profilu, a scenariusz 2 na kilkudziesięciu rozmowach - to wystarczy do
zmierzenia czasu do pierwszego fragmentu, choć nie do wysycenia workera.

## Dane testowe i sprzątanie

- Osobne konto firmy testowej, nie Twoje. Rozmowy z testu wchodzą do historii
  i do limitu wiadomości tego konta.
- Rozmowy z widgetu **liczą się** do statystyk (inaczej niż czat testowy panelu),
  więc po teście albo kasujemy konto testowe, albo czyścimy jego dane komendą
  retencji z `data_retention_days` ustawionym na krótki okres.
- Zapytania kontaktowe ze scenariusza 3 wysyłają powiadomienia e-mail na adres
  konta testowego - ustawić adres, którego nie czyta klient.

## Najbardziej prawdopodobne wąskie gardło

Wyszukiwanie wektorowe **nie ma indeksu**: `rag/engine.py` liczy `L2Distance`
po wszystkich fragmentach firmy, a w migracjach nie ma `ivfflat` ani `hnsw`.
Stąd liniowy wzrost w pomiarach z `accounts/plans.py`:

```
 5 140 fragmentów -> 0,19 s   (zmierzone)
25 700 fragmentów -> 1,04 s   (zmierzone)
51 400 fragmentów -> 2,41 s   (ekstrapolacja)
```

Przy jednoczesnych rozmowach ten czas mnoży się przez liczbę zapytań, a web ma
8 wątków (`gunicorn --threads 8`). Dlatego scenariusz 2 należy uruchomić na
koncie z **dużą** bazą wiedzy (25 MB i więcej), a nie na pustym - inaczej test
pokaże wynik, którego produkcja nie powtórzy.

Jeśli progi nie zostaną dotrzymane, kolejność poprawek (od najtańszej):

1. Indeks `ivfflat` albo `hnsw` na `DocumentChunk.embedding` - jedna migracja,
   kosztuje pamięć bazy, skraca wyszukiwanie do czasu stałego względem rozmiaru.
2. Ograniczenie `top_k` i progu odległości dla dużych baz wiedzy.
3. Więcej wątków albo instancji web na Renderze - dopiero tutaj rosną koszty.

## Stan wykonania

Krok 1 zrobiony: [pomiar z 16.09.2026](pomiar-obciazenia-lokalny.md), lokalnie
i na produkcji. Dwie poprawki do tego planu:

1. **Ruch musi pochodzić z wielu firm naraz.** Jedno konto trafia we własny limit
   planu, zanim zdąży obciążyć instancję, więc profil z jednym kluczem mierzy
   throttling, a nie system.
2. **Indeks wektorowy przed testem pojemności.** Na produkcji wyszukiwanie zajmuje
   303 ms przy 5 tysiącach fragmentów i około 1,4-2 s przy pełnym planie Pro, więc
   zjada większość trzysekundowego progu, zanim jeszcze odezwie się model. Test
   pojemności przed tą poprawką zmierzyłby stan, którego i tak nie chcemy zostawić.

## Kolejność wykonania

1. Zatwierdzasz narzędzie, środowisko i koszt scenariusza 2.
2. Piszę skrypt k6 z progami z SLO i dopisuję go do repozytorium razem z instrukcją.
3. Wariant A (lokalnie): pomiar wyjściowy, poprawki, powtórka.
4. Wariant C (produkcja, poza godzinami) albo B (staging), jeśli zdecydujesz.
5. Raport w `docs/`: data, wersja, zasoby, profil, wyniki p95, wnioski i decyzje.

## Decyzje, których potrzebuję

1. **Narzędzie:** k6 (rekomendacja) czy Locust?
2. **Środowisko:** A i C (bez kosztu hostingu) czy dokładamy B (efemeryczny staging)?
3. **Koszt scenariusza 2:** pełny profil (~700 rozmów) czy wersja tańsza
   (kilkadziesiąt rozmów)?
4. **Konto testowe:** zakładam nowe na produkcji czy używamy istniejącego konta
   demonstracyjnego?
