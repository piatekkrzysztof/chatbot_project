# Rejestracja i zaproszenia — F07, część 1

## Kontrakt API

Rejestracja firmy i przyjęcie zaproszenia wywołują walidatory Django z kontekstem
użytkownika. Minimum 8 znaków, brak hasła popularnego, wyłącznie numerycznego
lub zbyt podobnego do danych konta. Hasło ma do 1024 znaków; jego spacje nie są
obcinane. To dotyczy nowych haseł — istniejące hasła nie są zmieniane.

Nowe adresy przechodzą strip/lower. Nie usuwamy kropek, aliasów `+` ani innych
części adresu. Rejestracja używa e-maila jako username, dlatego ma limit 150
znaków. Zaproszenie ma osobny username (do 150 znaków) i e-mail do 254 znaków.
Zmiana e-maila w panelu podlega tej samej kontroli unikalności.

Indeks `account_email_ci_unique` obejmuje `lower(trim(email))`, z wyjątkiem
dotychczasowych pustych adresów. Nie przepisuje istniejących danych. Przy dwóch
równoległych zapisach duplikat daje 400, a transakcja wycofuje nową firmę i dane
rozliczeniowe. W okresie próbnym również utworzenie subskrypcji należy do tej
transakcji. Zewnętrzny Stripe jest wywoływany po niej; idempotencja i naprawa
nieudanego Checkout należą do F11.

Zaproszenie jest przeznaczone dla jednej osoby. Nowe `max_users` może wynosić
wyłącznie 1. Także stare zaproszenie z większym limitem przestaje być ważne po
pierwszym użyciu. Link bez adresata jest odrzucany; istniejących rekordów nie
kasujemy. Podgląd nadal zwraca dane adresata posiadaczowi losowego tokena.

Przyjęcie wymaga tego samego e-maila (bez rozróżniania wielkości liter).
Transakcja blokuje najpierw firmę, potem zaproszenie. Ponownie sprawdza token,
ważność, adresata i limit miejsc, tworzy użytkownika i zużywa token. Bezpośrednie
tworzenie konta używa tej samej blokady firmy. Cofanie i wystawianie zaproszeń
także blokuje firmę i ponownie sprawdza aktywnego właściciela. Cofnięcie wykonane
po udanym przyjęciu nie usuwa już utworzonego użytkownika.

## Limity i awarie

| Operacja | Na adres IP | Globalnie |
|---|---|---|
| Rejestracja | 5/godzinę | 30/minutę |
| Przyjęcie zaproszenia | 20/godzinę | 60/minutę |
| Podgląd zaproszenia | 60/minutę | 300/minutę |

Liczymy również błędne próby, w stałych oknach czasu. Na granicy okien możliwa
jest seria o podwójnej liczbie prób; nie deklarujemy przesuwanego okna. Cache
używa atomowych add/incr, adresy są zapisywane jako HMAC. HTTP 429 zawiera
Retry-After do następnego okna. Awaria cache lub produkcja bez współdzielonego
cache daje 503. Usunięcie danych z Redisa resetuje te limity — finansowe limity
wiadomości pozostają oddzielnie w PostgreSQL (F08).

IP pochodzi z istniejącego `client_ip`/`TRUSTED_PROXY_DEPTH`. Poprawność tej
wartości wymaga odbioru infrastruktury; źle dobrana liczba proxy może grupować
użytkowników albo ufać danym klienta. Nie zmieniamy jej w tej poprawce.

## Migracja i wdrożenie

1. Zastosuj standardową kopię przed migracją i sprawdź stan zadań.
2. `python manage.py migrate` wykona kontrolę konfliktów przed utworzeniem
   indeksu. Błąd podaje liczbę grup, bez publikowania adresów. Nie omijaj kontroli
   ani nie usuwaj losowego konta — ustal właściciela i sposób rozwiązania konfliktu.
3. Wdróż tę samą wersję 2.0.5 na web i workerze. Nie potrzeba nowej usługi ani
   nowego sekretu. `REDIS_URL` musi wskazywać dotychczasowy współdzielony Redis.
4. Na syntetycznych kontach sprawdź rejestrację, błędne hasło, odbiór zaproszenia,
   ponowne użycie, adresata, logowanie i limit miejsc. Nie wysyłaj rzeczywistych
   zaproszeń do klientów w ramach testu.

Odczyt produkcji 11.09.2026: zero grup duplikatów oraz zero zaproszeń bez
adresata/z większym limitem. To odczyt punktowy, nie zastępuje kontroli przy migracji.
W ramach przygotowania PR nie zmieniano produkcji ani kont użytkowników.

## Zakres nadal otwarty

To nie jest pełne zamknięcie F07. Rejestracja nadal nie wymaga potwierdzenia
skrzynki, a posiadanie linku zaproszenia jest uprawnieniem do jego użycia jako
wskazany adresat. Wymagane są kolejno ekrany aktywacji, ponawianie wiadomości,
jednorazowe tokeny potwierdzenia i ograniczenie nadużywania triali. Panel powinien
także usunąć wybór wielokrotnych użyć i jasno opisywać adresata zaproszenia.
MFA, reset hasła i zmiany cookie/CSRF pozostają etapami F14/F15/F22.
