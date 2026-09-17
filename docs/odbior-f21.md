# Odbiór F21: kopia, odtworzenie i alarmy

Stan na 17.09.2026, wersja 2.9.0. Protokół odbioru dla właściciela, **przeprowadzony
17.09.2026** - wyniki na końcu dokumentu. Kod kopii
i odtwarzania jest gotowy od 2.0.14 ([opis formatu](pelna-kopia-i-odtworzenie.md));
ten dokument dokłada brakujące kontrole i prowadzi przez odbiór krok po kroku.

Trzy warunki zamknięcia F21, wprost z [roadmapy](roadmapa-po-audycie.md):

1. rzeczywista kompletna kopia produkcji i jej **izolowane** odtworzenie na PostgreSQL 16,
2. **zmierzone** RPO i RTO, a nie zadeklarowane,
3. działający harmonogram i alarmy - **także przy braku przebiegu**.

Zielone CI na danych syntetycznych żadnego z nich nie zamyka.

## Co dokłada 2.9.0

| Polecenie | Co sprawdza | Gdzie ma chodzić | Potrzebuje klucza |
|---|---|---|---|
| `check_backup` (było) | treść i wiek najnowszej kopii dziennej | Render | tak |
| `kontrola_pelnej_kopii` (nowe) | treść, komplet i wiek najnowszej **pełnej** kopii | Render albo Twoja maszyna | tak |
| `kontrola_obecnosci_kopii` (nowe) | czy w magazynie w ogóle coś przybywa | **poza Renderem** | nie |

Pełna kopia (`backup_full`, format `.saas`) nie miała dotąd kontroli, która sama
znajdzie najnowszą: `verify_full_backup` wymaga podania nazwy pliku, więc nadaje
się do sprawdzenia konkretnej kopii, a nie do harmonogramu.

Trzecia kontrola istnieje dlatego, że kontrola uruchamiana na Renderze nie wykryje
awarii Rendera ani zatrzymania harmonogramu - milczy wtedy dokładnie tak samo,
jak przy spokoju. Działa bez klucza szyfrowania, żeby klucz odszyfrowujący
wszystkie kopie nie musiał trafiać do sekretów repozytorium. Odpowiada tylko na
pytanie „czy coś nowego się pojawiło"; treści pilnują dwie pozostałe.

Przebieg GitHub Actions: [`.github/workflows/kontrola-kopii.yml`](../.github/workflows/kontrola-kopii.yml),
na razie wyłącznie ręczny - harmonogram jest zakomentowany do czasu dodania sekretów.

## Zanim zaczniesz

- **Pełna kopia wymaga wstrzymania zapisów.** R2 i PostgreSQL nie mają wspólnej
  migawki, więc `backup_full` żąda flagi `--source-quiesced`, która jest Twoim
  oświadczeniem, a nie mechanizmem. To znaczy kilka minut przerwy w działaniu
  widgetu i panelu. Wybierz porę poza godzinami pracy klientów.
- **Nic nie kasujemy.** Ten odbiór niczego nie usuwa z produkcji ani z archiwum
  kopii. Retencja kopii i automatyczne usuwanie danych wchodzą dopiero po nim.
- **Sekrety wpisujesz Ty.** Wartości kluczy i tokenów nie należą do tego
  dokumentu ani do repozytorium.

## Krok A: pełna kopia produkcji

1. Zapisz porę rozpoczęcia okna.
2. Wstrzymaj zapisy: w panelu Rendera zatrzymaj (suspend) usługę web i worker
   (oraz beat, jeśli chodzi osobno). Poczekaj, aż trwające zadania się skończą.
   Nie uruchamiaj w tym czasie migracji ani ręcznych zmian w R2.
3. W powłoce usługi web (Render → Shell) uruchom:

```bash
python manage.py backup_full --source-quiesced --to-storage
```

4. Zapisz wypisaną nazwę kopii, liczbę plików i bajtów oraz porę zakończenia.
5. Wznów usługi. **Zapisz długość okna** - to jest realny koszt pełnej kopii.
6. Sprawdź kopię, nie ruszając produkcji:

```bash
python manage.py kontrola_pelnej_kopii
```

Wynik to JSON z nazwą, czasem snapshotu, liczbą plików i bajtów. Niezerowy kod
wyjścia znaczy, że kopii nie ma albo nie da się jej odczytać - wtedy przerwij
odbiór i zgłoś wynik, zamiast powtarzać okno.

## Krok B: izolowane odtworzenie

Odtwarzamy **na Twojej maszynie**, nie na Renderze. Pełna instrukcja z
uzasadnieniem każdego ograniczenia jest w
[pełnej kopii i odtworzeniu](pelna-kopia-i-odtworzenie.md#próba-odtworzenia--nowa-lokalna-baza);
tu skrót kolejności:

1. Pobierz kopię z R2 do prywatnego katalogu.
2. Przygotuj pustą bazę **PostgreSQL 16 z pgvector**, nazwaną `saas_restore_<cokolwiek>`.
   Polecenie odmawia pracy na innej nazwie, na zdalnym adresie i na Renderze.
   Najprościej kontenerem z tego samego obrazu, którego używa CI
   (`pgvector/pgvector:pg16`), na porcie innym niż zajęty przez bazę roboczą.
3. Uruchom proces bez produkcyjnego `.env`: ustaw `PYTHON_DOTENV_DISABLED=1`
   i podaj wyłącznie adres lokalnej bazy, `BACKUP_ENCRYPTION_KEY` oraz oryginalny
   `DJANGO_SECRET_KEY`. **Nie podawaj** Stripe, poczty ani dostępu do R2.

   Jeden wyjątek, znaleziony przy pierwszej próbie: `OPENAI_API_KEY` musi być
   **niepuste**, bo klient OpenAI powstaje przy imporcie ustawień i na pustym
   kluczu przewraca cały proces, zanim dojdzie do odtwarzania. Wystarczy wartość
   pozorna w rodzaju `nieuzywany-w-odtwarzaniu`: odtwarzanie i tak blokuje sieć
   poza portem lokalnej bazy, więc nie ma czym i dokąd zadzwonić.
4. `python manage.py migrate`, potem:

```bash
python manage.py restore_full_backup /prywatny/kopia.saas --output /prywatny/nowe-odtworzenie
```

Kod odtwarzania sam blokuje sieć i pocztę w swoim procesie, ale to dodatkowa
zapora, nie zamiennik izolacji środowiska.

## Krok C: co sprawdzić na odtworzonej bazie

Na jednej, wybranej firmie - najlepiej Twojej własnej, nie klienta:

| Sprawdzenie | Czego dowodzi |
|---|---|
| Logowanie i drugi składnik | hasła i sekrety MFA przeżyły kopię |
| Role: właściciel, pracownik, podgląd | uprawnienia nie zgubiły się po drodze |
| Odmowa dostępu do danych innej firmy | izolacja firm przeżyła odtworzenie |
| Pobranie pliku dokumentu | bajty plików wróciły, nie tylko wiersze |
| Treść i fragmenty wiedzy | wektory wróciły; bot ma z czego odpowiadać |

Nie wysyłaj z odtworzonego środowiska wiadomości, nie wołaj płatności ani modelu.

Część z tych sprawdzeń da się zrobić zapytaniami do odtworzonej bazy, bez
uruchamiania aplikacji i bez produkcyjnego klucza - wyniki z 17.09.2026 są
w sekcji „Wynik odbioru". Zapytania wypisują liczby i fakty, nie dane osobowe:
raport z odbioru nie ma powodu zawierać adresów ani nazwisk klientów.

## Krok D: pomiar RPO i RTO

Czas wypisany przez polecenie obejmuje tylko jego własny proces - to nie jest RTO.
Wypełnij tabelę własnymi pomiarami:

| Pozycja | Zmierzone 17.09.2026 | Uwagi |
|---|---|---|
| Długość okna wstrzymania zapisów (krok A) | ~2 min | prawie w całości klikanie w panelu Rendera |
| Czas tworzenia kopii | ~6 s | snapshot 10:00:16 UTC, nazwa nadana 10:00:22 |
| Rozmiar kopii | 3,54 MB danych / 4,73 MB szyfrogramu | rośnie z bazą wiedzy klientów |
| Czas pobrania kopii z R2 | poniżej minuty | plik 4,73 MB, pobranie z panelu Cloudflare |
| Czas przygotowania środowiska (baza, migracje) | ~3 min | kontener PG16 z obrazem CI, 90 migracji |
| Czas samego odtworzenia | **2,49 s** | wypisane przez polecenie |
| Czas sprawdzeń z kroku C | ~2 min | zapytania z tabeli wyżej |
| **RTO danych: do zweryfikowanej kopii lokalnie** | **~10 minut** | od pobrania kopii do sprawdzonych danych |
| **RTO produkcji: do działającej aplikacji** | **niezmierzone** | wymagałoby odbudowy usług i bazy na Renderze - patrz niżej |
| **RPO (wiek ostatniej zweryfikowanej kopii)** | **5 dni 15 godzin** | z braku harmonogramu, nie z tego testu |

**RTO produkcji jest nadal nieznane** i nie wolno tych dziesięciu minut brać za
czas powrotu do działania. Zmierzyliśmy odzyskanie **danych** do sprawdzonej
postaci. Odbudowa działającej usługi wymagałaby dodatkowo nowej instancji bazy
na Renderze, wgrania do niej danych, przestawienia zmiennych i wdrożenia - żaden
z tych kroków nie był dziś wykonywany, bo każdy dotyka produkcji.

**RPO wynika z częstotliwości, nie z powodzenia próby.** 5 dni 15 godzin to wiek
ostatniej kopii dziennej w chwili pomiaru: powstała 11.09.2026 o 18:32 UTC, ręcznie,
przy odbiorze F04. Bez harmonogramu każda kolejna liczba będzie równie przypadkowa.

RPO bierze się z tego, jak często kopia powstaje, a nie z powodzenia jednej próby.
Przy kopii dziennej RPO to do 24 godzin utraconych danych; przy pełnej kopii
raz w miesiącu - do miesiąca, jeśli dzienna zawiedzie.

## Krok E: harmonogram i alarmy

To jest warunek, o który najłatwiej się potknąć, bo wszystko wygląda dobrze,
dopóki nie sprawdzisz.

Wariant przyjęty 17.09.2026: **pełna kopia raz w miesiącu, ręcznie, bez
płatnych zadań na Renderze** (wariant 2 z sekcji „Wynik odbioru").

1. **Raz w miesiącu powtórz kroki A i B tego protokołu.** Kopia zajmuje około
   dwóch minut okna i kilka sekund liczenia; odtworzenie warto powtarzać
   rzadziej, ale przynajmniej po każdej zmianie schematu bazy.
2. **Po każdym oknie sprawdź kopię:** `python manage.py kontrola_pelnej_kopii`.
   Odpowiedź inna niż `status: ok` znaczy, że okno trzeba powtórzyć.
3. **Włącz niezależny monitor** (bez kosztu): w repozytorium backendu dodaj
   sekrety `BACKUPS_STORAGE_BUCKET_NAME`, `BACKUPS_ACCESS_KEY_ID`,
   `BACKUPS_SECRET_ACCESS_KEY`, `BACKUPS_S3_ENDPOINT_URL` z tokenu R2 **tylko do
   odczytu i listowania**, a potem odkomentuj `schedule` w
   [`kontrola-kopii.yml`](../.github/workflows/kontrola-kopii.yml). Przebieg
   sprawdza wyłącznie archiwum pełnych kopii, co tydzień, z progiem 31 dni -
   czyli odzywa się dokładnie wtedy, gdy miesiąc minął, a kopii nie ma.
4. **Sprawdź alarm, zamiast zakładać, że działa.** Uruchom przebieg ręcznie
   z progiem `--pelna-godzin 1`: ma zejść czerwony, a powiadomienie ma trafić do
   Twojej skrzynki. Dopiero to jest dowodem. Zapisz datę tej próby.

Gdy pojawi się ruch, który miesięcznej straty nie zniesie, wraca wariant 3:
[zadanie cron kopii dziennej](render-backups.example.yaml) plus `check_backup`
z progiem 30 godzin i dopisanie `dzienna` do `--archiwa` w monitorze.

| Alarm | Wywołany próbnie | Powiadomienie odebrane |
|---|---|---|
| Brak pełnej kopii (`kontrola_pelnej_kopii`) | 17.09.2026 - odpowiedziało „Brak pełnych kopii w prywatnym magazynie" przed pierwszym oknem | nie dotyczy, uruchomione ręcznie |
| Kopia starsza niż próg (GitHub Actions, `--pelna-godzin 1`) | 17.09.2026, 14:21 UTC - przebieg czerwony, `Najnowsza kopia w full-backups ma 4.4 h, próg to 1.0 h` | **tak**, potwierdzone przez właściciela |

Pierwsza próba tego alarmu, 17.09.2026 o 13:24 UTC, **wykryła usterkę w samym
przebiegu**: kontrola poprawnie odmówiła i wypisała powód, a przebieg mimo to
zszedł na zielono, bo polecenie szło przez potok bez `set -o pipefail` i kodem
wyjścia był kod `tee`. Alarm był skonfigurowany, podpięty i niemy. Naprawione
w 2.9.2 razem z testem regresji.

To jest cały powód, dla którego ten krok jest w protokole: usterki nie znalazł
przegląd kodu ani zielone CI, tylko umyślne wywołanie fałszywego alarmu.

## Krok F: sprzątanie

Usuń wyłącznie testową bazę `saas_restore_*` i prywatny katalog próby. Nie usuwaj
kopii, kluczy ani niczego z produkcji. Zapisz wynik odbioru w tym dokumencie:
datę, wersję kodu, zmierzone czasy i wykryte problemy.

## Wynik odbioru - 17.09.2026

Wersja kodu: 2.9.0 (produkcja i środowisko próby). Kopia
`full-backups/full-20260917-100022-...saas`, snapshot 10:00:16 UTC.

### Zaliczone

| Warunek | Dowód |
|---|---|
| Pierwsza pełna kopia produkcji w historii projektu | `backup_full --source-quiesced --to-storage`, zweryfikowana ponownym odczytem z R2 |
| Kopia jest kompletna | 1 plik w kopii wobec 1 dokumentu z plikiem, 0 logo i 0 awatarów w bazie; rozmiar obiektu w R2 zgodny co do bajta |
| Izolowane odtworzenie na PostgreSQL 16 | kontener `pgvector/pgvector:pg16`, baza `saas_restore_probny`, 2,49 s |
| Dane wróciły w całości | 2 firmy, 3 konta (1 właściciel, 2 podglądy), 2 subskrypcje, 27 dokumentów, 320 fragmentów, 86 rozmów, 188 wiadomości |
| Relacje przetrwały | 0 dokumentów bez firmy, 0 kont bez firmy, 0 fragmentów bez dokumentu |
| Hasła przetrwały | 3 z 3 kont ze skrótem `pbkdf2_`, nie pustym polem |
| Wektory przetrwały | wymiar 512 zgodny z kodem, wartości niezerowe |
| Bajty plików przetrwały | odtworzony PDF zaczyna się od `%PDF-1.7`, 187 805 B - tyle samo, co obiekt w R2 |
| Klucze widgetu przetrwały | unikalne i niepuste |
| Zgodność kluczy wymuszona | polecenie liczy dowód z `DJANGO_SECRET_KEY` i odmówiłoby przy innym |

### Zaliczone: alarmy i harmonogram

Warunek zamknięty **17.09.2026**: przebieg [`kontrola-kopii.yml`](../.github/workflows/kontrola-kopii.yml)
chodzi w każdy poniedziałek o 06:20 UTC, próbny fałszywy alarm zszedł czerwony,
a powiadomienie dotarło do właściciela. Harmonogram włączył właściciel osobiście,
bo GitHub kieruje powiadomienia o nieudanym przebiegu zaplanowanym do osoby,
która ostatnio zmieniała linię `cron`.

Poniżej zapisana decyzja o częstotliwości kopii, bo od niej zależy deklarowane RPO.

Właściciel zdecydował 17.09.2026, że **nie uruchamiamy płatnego zadania cron na
Renderze**. Decyzja świadoma, zapisana tutaj razem z jej ceną: bez harmonogramu
kopia powstaje wtedy, gdy ktoś o niej pamięta, więc RPO pozostaje nieokreślone.
Zmierzone dziś 5 dni 15 godzin nie jest gwarancją, tylko fotografią jednego dnia.

Monitor braku przebiegów (`kontrola_obecnosci_kopii` w GitHub Actions) jest gotowy,
ale włączony teraz świeciłby na czerwono codziennie - i słusznie, bo kopie dzienne
faktycznie nie powstają. Alarm, który zapala się zawsze, przestaje być alarmem.

**Wybrany wariant (17.09.2026): pełna kopia raz w miesiącu, ręcznie**, plus
niezależny monitor z progiem 31 dni na archiwum pełnych kopii. Koszt: zero
pieniędzy i kilka minut miesięcznie. Deklarowane RPO: **do miesiąca** - i to jest
liczba, którą wolno podawać klientowi, bo wynika z ustalonej częstotliwości,
a nie z jednego udanego dnia.

Monitor sprawdza **wyłącznie archiwum pełnych kopii**. Archiwum kopii dziennych
zostaje bez harmonogramu, więc pilnowanie go oznaczałoby cotygodniowy alarm
o decyzji, a nie o awarii - dlatego `--archiwa` pozwala je pominąć, a wynik
kontroli wypisuje, czego dotyczył.

Odrzucone świadomie:

1. **Nic.** RPO nieokreślone. Odrzucone, bo „nie wiemy" nie jest odpowiedzią,
   którą da się dać klientowi pytającemu o kopie.
2. **Cron kopii dziennej na Renderze**, RPO do 24 godzin. Odłożone: osobno
   rozliczana usługa, a przy dzisiejszym ruchu (2 firmy, 86 rozmów) miesięczna
   kopia jest proporcjonalna. Wraca, gdy pojawi się klient, którego miesięczna
   strata danych by dotknęła.

Monitor jest włączony, a alarm sprawdzony i odebrany - szczegóły w tabeli
w kroku E. **F21 zamknięte 17.09.2026.**

### Czego ten odbiór nie dowodzi

- **RTO produkcji.** Zmierzone zostało odzyskanie danych, nie powrót usługi.
- **Logowania i drugiego składnika end-to-end.** Sprawdzone strukturalnie: skróty
  haseł są na miejscu. Drugiego składnika nie ma dziś na produkcji ani jednego
  (0 wpisów), więc nie było czego odtwarzać. Warto wiedzieć, że nasiona TOTP są
  szyfrowane kluczem wyprowadzonym z `DJANGO_SECRET_KEY`: odtworzenie z innym
  kluczem zamknęłoby dostęp wszystkim, którzy mają włączony drugi składnik.
  Polecenie temu zapobiega, odmawiając pracy przy niezgodnym kluczu.
- **Retencji kopii.** Archiwum nie jest sprzątane; nic dziś nie usunęliśmy.

**F21 zamknięte 17.09.2026.** Odblokowuje to retencję z F20: okresy przechowywania
i harmonogram usuwania czekały właśnie na odbiór odtwarzania.

Co zostaje w rytmie miesięcznym, po stronie właściciela: powtórzenie kroków A i B
(okno, kopia, sprawdzenie). Monitor złapie zapomnienie dopiero po 31 dniach - jest
siatką bezpieczeństwa, nie przypomnieniem.
