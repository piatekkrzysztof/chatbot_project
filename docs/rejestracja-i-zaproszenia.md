# Rejestracja i zaproszenia — F07, część 1

Opis etapu 2.0.5. Wersja 2.0.6 zmienia publiczną rejestrację na potwierdzenie
e-maila przed utworzeniem konta: [aktualny kontrakt](aktywacja-konta.md).

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

## Powtórny okres próbny na tę samą skrzynkę (2.17.0)

Potwierdzenie adresu daje 14 dni i 2000 wiadomości, czyli **6-10 zł kosztu
modelu** po naszej stronie. Okres próbny przysługuje adresowi - a adresów
jednej skrzynki jest wiele. `jan+sklep@gmail.com`, `jan+bot@gmail.com`
i `j.a.n@gmail.com` to jedno pudełko i jeden człowiek; dla bazy to trzy obce
konta i trzy okresy próbne. Do 2.17.0 nic tego nie zauważało.

Przy zakładaniu okresu próbnego liczymy skrót skrzynki
(`accounts/adresy.py`) i zapisujemy go przy firmie. Jeśli ten sam skrót ma już
inna firma, na `EMAIL_ALERTOW` idzie zgłoszenie z numerami firm.

**Zgłaszamy, nie odmawiamy** - decyzja właściciela z 29.09.2026. Konto powstaje
normalnie i okres próbny też. Powód: nie wiemy jeszcze, czy to się w ogóle
zdarza, a odmowa uczciwemu klientowi kosztuje więcej niż dziesięć złotych.
Bywa to zupełnie niewinne - ta sama osoba zakłada konto drugiej firmie albo
wraca po przerwie. Gdy okaże się, że zdarza się regularnie, odmowa jest zmianą
jednego miejsca w `zalozenie_okresu_probnego`.

### Co dokładnie uznajemy za tę samą skrzynkę

| Reguła | Gdzie | Dlaczego |
|---|---|---|
| Wielkość liter bez znaczenia | wszędzie | `JAN@` i `jan@` to zawsze jedna skrzynka |
| Znacznik po `+` obcięty | wszędzie | konwencji z RFC 5233 używa świadomie właściciel skrzynki, nikt inny |
| Kropki obcięte | tylko Gmail | `j.an@` i `jan@` to jedna skrzynka w Gmailu, ale **dwie różne** u większości pozostałych dostawców |
| `googlemail.com` = `gmail.com` | - | ten sam dostawca pod inną nazwą |

Granica przy kropkach jest celowa: `j.kowalski@firma.pl` i `jkowalski@firma.pl`
to zwykle dwie osoby, a alarm zapalany na dwóch obcych ludzi przestaje być
czytany.

### Czego nie zapisujemy

Przy firmie leży **skrót**, nie adres. Do rozpoznania powtórki wystarcza
porównanie równości, a drugi adres e-mail obok istniejącego `owner_email` byłby
kopią danych osobowych trzymaną na wszelki wypadek. Solą jest klucz Django,
więc skrótu nie da się porównać z niczym spoza tej instalacji.

Sama wiadomość alarmowa też nie zawiera adresu - podaje numery firm. Alarm to
kolejne miejsce, w którym dane osobowe wychodzą poza bazę, tym razem do
skrzynki operatora i na serwer poczty. Kto chce zobaczyć adresy, otwiera panel
administracyjny, gdzie taki odczyt zostawia wpis w dzienniku.

### Wdrożenie

Migracja `accounts.0040_skrot_skrzynki` dodaje jedno pole tekstowe z indeksem.
U firm sprzed 2.17.0 zostaje puste i nie jest uzupełniane wstecz: policzenie
skrótów istniejącym firmom dałoby alarmy o rejestracjach sprzed miesięcy,
których i tak byśmy nie cofnęli. Wykrywanie dotyczy kont zakładanych od
wdrożenia.

## Zakres nadal otwarty

To nie jest pełne zamknięcie F07. Posiadanie linku zaproszenia jest nadal
uprawnieniem do jego użycia jako wskazany adresat, a panel powinien usunąć
wybór wielokrotnych użyć i jasno opisywać adresata zaproszenia. Zostaje też
rzeczywisty odbiór poczty aktywacyjnej i potwierdzenie `TRUSTED_PROXY_DEPTH`
na produkcji. MFA, reset hasła i zmiany cookie/CSRF pozostają etapami
F14/F15/F22.

Zamknięte od czasu pierwszej wersji tego dokumentu: potwierdzenie skrzynki
przed założeniem konta, ekrany aktywacji w panelu (`/potwierdz-email`,
`/aktywacja`), ponawianie wiadomości z limitem, jednorazowe tokeny
potwierdzenia i - opisane wyżej - rozpoznawanie powtórnych okresów próbnych.
