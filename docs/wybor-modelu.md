# Wybór modelu czatu - pomiar 8.10.2026 (2.27.0)

## Skąd pytanie

Test bota na ofercie cateringu z PDF-a (po 2.26.0 wyszukiwanie znalazło
właściwy fragment): „Co jeśli odwołam przyjęcie 10 dni wcześniej?” - bot
odpowiedział „zwrócimy całą zaliczkę”, a dokument mówi „Od 13 do 5 dni -
zwracamy połowę”. Z tym samym promptem i fragmentem gpt-4o-mini mylił się
5 razy na 5; gpt-4.1-mini i gpt-4o - 0 na 5. Najtańszy model nie dopasowuje
liczby do przedziału, a regulaminy klientów są pełne takich progów (zwroty,
rabaty od X osób, dopłaty za kilometry).

## Jak mierzono

[`narzedzia/ocena_modeli/ocena.py`](../narzedzia/ocena_modeli/ocena.py),
cztery dokumenty testowe obok (cennik DOCX z tabelą, zasady przechowywania
TXT w Windows-1250, regulamin PDF, oferta cateringu PDF). Każdy model dostaje
**identyczny kontekst**: fragmenty z podziału i wyszukiwania 2.26.0 i prompt
systemowy z produkcji. Odpowiedzi strumieniem, jak w widgecie. Grupy pytań:
fakty wprost, wnioskowanie (przedział, mnożenie, rabat, „najtańsza gratis”,
minimum osób), pytania spoza wiedzy (odmowa ze znacznikiem
`[BRAK_ODPOWIEDZI]`) i uprzejmości. Ceny: cennik OpenAI z 8.10.2026,
kurs 4 zł za USD.

## Wyniki

### Runda 1 - przegląd (1 powtórzenie, 35 pytań)

Odpadli:

- **gpt-5-nano, gpt-5-mini** - 24 i 11 pustych odpowiedzi: cały limit
  `OPENAI_MAX_OUTPUT_TOKENS` (600) idzie na rozumowanie.
- **gpt-4.1-mini** - odmawia bez znacznika w połowie pytań spoza wiedzy, więc
  luki w wiedzy nie trafiałyby do raportu.
- **gpt-6.1-sol** - jakość jak gpt-6-luna, koszt wiadomości ~20 razy wyższy.

W tej rundzie dane miały sprzeczności (dwa dokumenty tej samej cukierni
z różnymi terminami anulowania). Lepsze modele je wyłapywały i odmawiały -
test liczył to jako błąd. W rundzie 2 sprzeczny dokument usunięto.

### Runda 2 - kandydaci (2 powtórzenia, 37 pytań)

| Model | Fakty | Wnioskowanie | Odmowy | Koszt / wiadomość | Pierwsze słowa (mediana / p95) |
|---|---|---|---|---|---|
| gpt-4o-mini (do 2.27.0) | 32/32 | 9/14 | 16/16 | 0,0006 zł | 0,5 / 0,9 s |
| gpt-5.4-nano | 32/32 | 10/14 | 16/16 | 0,0009 zł | 0,6 / 0,9 s |
| gpt-5.4-mini | 31/32 | 10/14 | 16/16 | 0,0034 zł | 0,8 / 1,5 s |
| gpt-5.6-luna | 32/32 | 11/14 | 16/16 | 0,0009 zł | 0,8 / 2,2 s |
| gpt-6-luna (domyślnie) | 32/32 | 13/14 | 16/16 | 0,0005 zł | 2,0 / 4,0 s |

### Runda 3 - gpt-6-luna i `reasoning_effort` (3 powtórzenia)

| Wysiłek | Fakty | Wnioskowanie | Prawdziwe błędy* | Odmowy | Koszt | Pierwsze słowa |
|---|---|---|---|---|---|---|
| `low` | 48/48 | 18/21 | 1 na 18 | 24/24 | 0,0004 zł | 0,8 / 1,5 s |
| **`medium`** | 48/48 | 18/21 | **0 na 18** | 24/24 | 0,0005 zł | 1,1 / 2,6 s |
| `high` | 48/48 | 18/21 | 0 na 18 | 24/24 | 0,0005 zł | 1,0 / 2,1 s |

\* Trzy „błędy” w każdym wariancie to pytanie o dowóz na 40 km: regulamin
cukierni i oferta cateringu podają różne stawki, a model to zgłaszał. Pytanie
usunięte z narzędzia w repozytorium. `low` raz na trzy próby źle policzył
„3 dekoracje, najtańsza gratis” (75 zł).

### Bramka z repozytorium - `ocen_generowanie` (sklep rowerowy, 3 powtórzenia)

| | gpt-4o-mini | gpt-6-luna, `medium` |
|---|---|---|
| odmowy trafne | 100% | 100% |
| odmowy fałszywe | 0% | 0% |
| odmowy na uprzejmości | 0% | 0% |
| oparte na wiedzy | 100% | 100% |
| tokenów na odpowiedź | 779 | 796 |
| czas całej odpowiedzi | 0,96 s | 1,88 s |

## Decyzja: gpt-6-luna, `reasoning_effort=medium`

- **Mądrzejszy:** bez błędów wnioskowania, gdzie gpt-4o-mini mylił się
  w 3 z 12 prób - nie licząc pytania ze sprzecznymi danymi (dwa razy
  przedział zwrotu zaliczki, raz rabat „najtańsza gratis”).
  Fakty, odmowy i bramka `ocen_generowanie` bez różnic.
- **Tańszy:** ~0,0005 zł zamiast ~0,0006 zł na wiadomość w pomiarze.
  Wejście kosztuje 0,10 zamiast 0,15 USD za milion tokenów, a to wejście
  (wiedza w prompcie) jest większością kosztu - patrz
  [koszt-klienta.md](koszt-klienta.md).
- **Wolniej zaczyna:** pierwsze słowa w medianie ~1,1 s zamiast 0,5 s, p95
  ~2,6 s. Na produkcji dochodzi wyszukiwanie, więc to blisko celu „p95
  poniżej 3 s” z [SLO](slo-i-czasy-odpowiedzi.md). `medium` zamiast `high`:
  ta sama jakość, a przy trudniejszych pytaniach `high` może myśleć dłużej.
  Gdy czas okaże się za długi, `low` zmienia się samą zmienną środowiskową.

Granice: 32-37 pytań do dokumentów testowych, 2-3 powtórzenia. To podstawa
do decyzji, nie dowód na każdą bazę wiedzy.

## Co zmienia 2.27.0 w kodzie

- `OPENAI_REASONING_EFFORT` - wysyłany tylko, gdy ustawiony. gpt-4o-mini
  odrzuca ten parametr błędem 400, tak jak gpt-6-luna temperaturę 0,2.
- `sprawdz_model` sprawdza też ścieżkę strumieniową (widget), traktuje pustą
  odpowiedź jako porażkę, podpowiada przy odrzuconym `reasoning_effort`
  i kończy się kodem 1 przy niepowodzeniu.

## Przełączenie na produkcji (kolejność ma znaczenie)

1. Wdrożyć 2.27.0. Sam kod niczego nie zmienia: bez nowej zmiennej
   parametry są takie jak dotąd.
2. Render → Environment, w jednym zapisie:
   - `OPENAI_TEMPERATURE` - **pusta wartość** (gpt-6-luna odrzuca 0,2 -
     bez tego każde pytanie kończy się komunikatem awaryjnym),
   - `OPENAI_REASONING_EFFORT` = `medium`,
   - `OPENAI_CHAT_MODEL` = `gpt-6-luna`.
3. Po restarcie: Render → Shell → `python manage.py sprawdz_model`. Musi być
   „DZIALA” i czas pierwszych słów. Przy „NIE DZIALA” - od razu powrót.
4. Test bota: „Co jeśli odwołam przyjęcie 10 dni wcześniej?” na ofercie
   cateringu - oczekiwana połowa zaliczki.
5. Przez kilka dni: linie „Wolne żądanie” w logu i czas odpowiedzi w Sentry
   (cel: pierwszy fragment p95 poniżej 3 s).

**Powrót:** `OPENAI_CHAT_MODEL=gpt-4o-mini`, `OPENAI_TEMPERATURE=0.2`,
`OPENAI_REASONING_EFFORT` pusta. Bez wdrożenia kodu.

## Przełączenie na produkcji - 8.10.2026

2.27.0 wdrożone, zmienne ustawione (`OPENAI_TEMPERATURE` puste,
`OPENAI_REASONING_EFFORT=medium`, `OPENAI_CHAT_MODEL=gpt-6-luna`),
`sprawdz_model` - „DZIALA”. Właściciel potwierdził działanie w Test bota.

## Ryzyka do obserwacji

- **Pusta odpowiedź:** limit 600 tokenów obejmuje rozumowanie. Przy `medium`
  model zużywał średnio ~50 tokenów, ale bardzo trudne pytanie może zjeść
  limit. **Od 2.28.0** pusta odpowiedź (także same białe znaki) idzie drogą
  awarii: odwiedzający dostaje komunikat zamiast pustego dymka, wiadomość nie
  jest naliczana, a w logu (i w Sentry) jest błąd „Pusta odpowiedź modelu”.
  Do 2.28.0 widget pokazywał pusty dymek bez śladu, a ścieżka bez strumienia
  najpierw naliczała wiadomość, potem padała na pustej treści. Kilka takich
  wpisów dziennie - podnieść `OPENAI_MAX_OUTPUT_TOKENS` albo obniżyć
  `OPENAI_REASONING_EFFORT`.
- **Model wycofany albo zmieniony przez OpenAI** - `sprawdz_model` po każdej
  zmianie zmiennych i przy niepokojących zgłoszeniach.
