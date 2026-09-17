# Monitoring dostępności

Stan na 17.09.2026, wersja 2.11.1. Czego dziś brakuje: **nikt z zewnątrz nie
sprawdza, czy aplikacja żyje.**

## Po co, skoro są już czuwania

Czuwania w kodzie (odmowy widgetu co godzinę, cisza widgetu, rozmiar bazy
wiedzy) pilnują objawów u klientów i działają dobrze. Mają jedną wspólną wadę:
**wszystkie chodzą na Renderze**. Gdy padnie Render, nie zaalarmuje nic - bo
alarmować miałoby to, co właśnie przestało działać.

To dokładnie ta sama pomyłka, którą 17.09.2026 złapaliśmy przy kopiach: monitor
był skonfigurowany, podpięty i niemy. Różnica jest taka, że tam wystarczył
przebieg raz w tygodniu, a dostępność trzeba sprawdzać co kilka minut.

`/health/` istnieje od 2.0.3 i zwraca wszystko, czego monitor potrzebuje.
Sprawdzany jest jednak ręcznie, przy wdrożeniach. Między wdrożeniami nikt nie
patrzy, więc o awarii dowiadujesz się od klienta - albo wcale, bo klient po
prostu przestaje wracać.

## Dlaczego nie GitHub Actions

Przy kopiach monitor chodzi w GitHub Actions i to jest dobre rozwiązanie: raz
w tygodniu, czyli cztery przebiegi miesięcznie. Do dostępności się nie nadaje
i decyduje o tym arytmetyka, a nie elegancja:

| Częstotliwość | Przebiegów miesięcznie | Minut z limitu 2 000 |
|---|---|---|
| co 5 minut | 8 640 | 8 640 |
| co 10 minut | 4 320 | 4 320 |
| co 30 minut | 1 440 | 1 440 |

GitHub rozlicza **każde uruchomienie jako co najmniej minutę**, niezależnie od
tego, że samo `curl` trwa sekundę. Nawet wariant półgodzinny zjadłby prawie
cały darmowy limit, z którego dziś korzysta CI - a półgodzinne okno i tak jest
za długie, żeby nazwać to monitoringiem.

## Co ustawić

Usługa zewnętrzna z darmowym planem: UptimeRobot, Better Stack albo dowolna
inna z alarmem na e-mail. Poniżej ustawienia niezależne od wyboru.

### Monitor 1: aplikacja odpowiada i baza działa

| Ustawienie | Wartość |
|---|---|
| Typ | HTTP(s) ze słowem kluczowym |
| Adres | `https://<adres-backendu>/health/` |
| Szukane słowo | `"stan": "ok"` |
| Alarm gdy | słowa **brak** |
| Częstotliwość | 5 minut |
| Próg alarmu | 2 kolejne nieudane sprawdzenia |

Dwa kolejne, nie jedno: pojedyncze zerwane połączenie zdarza się bez awarii,
a alarm, który budzi przy każdym drgnięciu sieci, po tygodniu przestaje być
czytany. Dwa sprawdzenia to około 10 minut do wykrycia - przy dzisiejszej skali
w zupełności wystarczy.

### Dlaczego słowo kluczowe, a nie sam kod odpowiedzi

`/health/` zwraca 503 tylko wtedy, gdy nie odpowiada **baza**. Gdy padnie Redis
albo worker, odpowiedź ma kod 200 i `"stan": "ograniczony"` - czat i panel
działają, ale w tle nie dzieje się nic: embeddingi nie powstają, strony się nie
odświeżają, powiadomienia o zmianie hasła nie wychodzą, retencja nie sprząta.

Monitor patrzący wyłącznie na kod odpowiedzi świeciłby wtedy na zielono. To ten
sam rodzaj cichej awarii, którą tępimy w całym projekcie, tylko przeniesiony
o poziom wyżej - dlatego szukamy `"stan": "ok"`, a nie „strona się otworzyła".

### Monitor 2 (opcjonalny): widget odpowiada odwiedzającym

| Ustawienie | Wartość |
|---|---|
| Adres | `https://<adres-backendu>/api/widget-settings/` z nagłówkiem klucza firmy testowej |
| Alarm gdy | kod inny niż 200 |
| Częstotliwość | 5 minut |

Monitor 1 sprawdza aplikację od środka, ten - drogę, którą chodzi odwiedzający
strony klienta. Jeśli usługa zewnętrzna nie umie wysyłać nagłówków, pomiń go:
monitor 1 wyłapie każdą awarię, która dotyka obu.

## Sprawdzenie alarmu

**Konfiguracja alarmu nie jest dowodem, że alarm dochodzi.** 17.09.2026 monitor
kopii przeszedł tę próbę na czerwono i dopiero ona pokazała, że powiadomienie
nie wychodzi.

Sposób bez dotykania produkcji: dodaj tymczasowo monitor na adres, który na
pewno nie istnieje (`/health-nieistniejacy/` na tym samym serwerze), poczekaj
na alarm, potwierdz odbiór wiadomości i skasuj monitor. Zapisz datę tej próby.

| Alarm | Wywołany próbnie | Powiadomienie odebrane |
|---|---|---|
| Aplikacja nie odpowiada | | |

## Czego ten monitoring nie daje

- **Nie mierzy czasu odpowiedzi pod obciążeniem.** To osobny temat -
  [plan testu obciążeniowego](test-obciazeniowy.md).
- **Nie wykryje awarii dotyczącej jednego klienta** (zły klucz widgetu,
  wyczerpany limit planu). Od tego są czuwania w kodzie i ekran „Stan systemu".
- **Nie zastąpi strony statusu.** Mówi Tobie, że coś padło; klientowi nie mówi
  nic. Przy dzisiejszej liczbie klientów wystarczy wiadomość od Ciebie.
