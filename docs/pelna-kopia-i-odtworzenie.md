# Pełna kopia aplikacji i lokalna próba odtworzenia — 2.0.14

Ten etap dodaje ręczne narzędzia kopii i odtwarzania. Sam deploy nie tworzy kopii,
nie zatrzymuje usług i nie uruchamia odtwarzania. Produkcyjna próba, pomiar RPO/RTO,
harmonogram oraz niezależne alarmowanie pozostają do odbioru.

## Zakres

- Dane modeli SaaS, w tym użytkownicy, firmy, role, uprawnienia grup, MFA,
  subskrypcje, rozmowy, wiedza, wektory, sesje i kolejka powiadomień.
- Bajty każdego pliku wskazanego przez Document.file, Tenant.widget_logo
  i Tenant.widget_avatar. Jeden wspólny obiekt nie jest kopiowany wielokrotnie;
  manifest zapisuje wszystkie odwołania do niego.
- Wersja aplikacji/PostgreSQL, lista migracji, czas snapshotu, liczby rekordów,
  nazwy i powiązania plików, rozmiary oraz sumy kontrolne. Nowe nieobsługiwane
  pole FileField blokuje kopię, zamiast pozostawać niezauważone.

Nie obejmuje: osobnej bazy formularza marketingowego, obiektów bez odwołania
w bazie, ról/grantów PostgreSQL, konfiguracji Rendera/R2/DNS ani PITR. Jak wcześniej
pomijamy contenttypes, auth.permission, sessions i admin.logentry. Content types
i uprawnienia odtwarza `migrate`; relacje do nich korzystają z kluczy naturalnych.
Sesje aplikacji LoginSession są objęte kopią. Dane modeli nie zastępują fizycznej
kopii instancji PostgreSQL. Starsze `backup_data`, `decrypt_backup` i `check_backup`
zachowują dotychczasowy format i działanie.

## Spójność i wymagane wstrzymanie zapisów

Baza jest czytana w jednej transakcji PostgreSQL REPEATABLE READ, READ ONLY.
Dotyczy to również listy odwołań do plików, schematu migracji i danych modeli.
Zrzut zwykłymi kolejnymi zapytaniami bez tego snapshotu mógłby mieszać stany bazy.
[Izolacja transakcji PostgreSQL](https://www.postgresql.org/docs/16/transaction-iso.html).

R2 i PostgreSQL nie współdzielą snapshotu. Dlatego ta wersja wymaga wstrzymania
zapisów przed `--source-quiesced`. Flaga jest oświadczeniem operatora, a nie
mechanizmem zatrzymującym usługi. Należy wstrzymać nowe żądania zapisujące,
poczekać na zakończenie trwających operacji i wstrzymać worker/beat oraz inne
procesy modyfikujące dane lub pliki. Nie wykonywać równocześnie migracji,
retencji, ręcznych zmian w R2 ani operacji administratora.

Brak któregokolwiek wskazanego pliku przerywa tworzenie kopii. Nie raportujemy
takiej kopii jako kompletnej. Wstrzymanie zapisów jest konieczne również przy
publicznych plikach, które mogą zostać nadpisane pod tą samą nazwą. Przed pierwszą
próbą produkcyjną trzeba uzgodnić okno, przygotować sposób wznowienia usług
i oszacować czas z rzeczywistego wolumenu. Nie deklarujemy kopii bez przestoju.

## Format i ograniczenia zasobów

Plik `.saas` to ZIP_STORED zawierający wyłącznie zaszyfrowane części `data/...`
oraz zaszyfrowany `manifest.fernet`. Nie jest zwykłym ZIP-em z jawnymi dokumentami.
Fernet wymaga całej wiadomości w pamięci, dlatego każdy fragment ma najwyżej
1 MiB. Manifest wiąże kolejność, rozmiary i SHA-256 szyfrogramów oraz sumy
całych plików. Używamy istniejącego BACKUP_ENCRYPTION_KEY.
[Fernet i ograniczenia pamięci](https://cryptography.io/en/latest/fernet/).

- Limit danych przed szyfrowaniem: 512 MiB; część bazy dodatkowo ogranicza
  istniejące BACKUP_MAX_BYTES (100 MiB). Maksymalnie 4096 elementów ZIP i 4094
  odwołania do plików; manifest do 2 MiB.
- Szyfrowanie zwiększa rozmiar; na źródle trzeba zapewnić miejsce na tymczasowy
  szyfrogram, a przy odtwarzaniu również na odszyfrowane dane i bazę.
- Pliki przetwarzamy blokami. Modele czytamy po jednym rekordzie; pojedynczy
  rekord/tekst nadal musi zmieścić się w pamięci. Limity nie zastępują pomiaru
  na rzeczywistych danych i zasobach instancji.
- Parser ogranicza rozmiar katalogu ZIP przed jego wczytaniem. Odrzuca
  kompresję, ZIP64, duplikaty, nadmiarowe/brakujące części, niezgodne rozmiary,
  sumy, niewłaściwy klucz i niebezpieczne nazwy. Nie używa extractall.
- Na źródle tymczasowy plik zawiera tylko szyfrogram. Jawne dane powstają
  dopiero w nowym prywatnym katalogu docelowym (pliki 0600, katalog 0700 tam,
  gdzie system egzekwuje te tryby; na Windows sprawdzić dziedziczone ACL).

Nazwy i adresy z bazy są wewnątrz szyfrowania. Rozmiar archiwum/liczba części
oraz czas tokenów Fernet nie są ukrywane. Klucz odszyfrowujący daje też możliwość
utworzenia poprawnie podpisanej kopii, dlatego kopie kluczy należy chronić.

## Utworzenie i weryfikacja

Po przygotowaniu okna i faktycznym wstrzymaniu zapisów, w środowisku źródłowym:

```text
python manage.py backup_full --source-quiesced --to-storage
```

Zapis trafia do `full-backups/` w istniejącym prywatnym magazynie kopii.
Sukces wymaga ponownego odczytu i pełnej weryfikacji wszystkich części oraz
zgodności manifestu z wysłanym. Nie wymaga nowego bucketa ani klucza. Po wyniku
lub błędzie wznowić usługi według wcześniej przygotowanej instrukcji.

Alternatywnie `--output /prywatny/katalog/nowa-kopia.saas` zapisuje nowy plik
lokalny; katalog nadrzędny musi istnieć. Istniejący plik ani publiczny MEDIA_ROOT
nie mogą być celem. Można połączyć oba rodzaje zapisu; przy błędzie zdalnego
zapisu poprawna kopia lokalna może już istnieć.

Kontrola konkretnej kopii, bez odtwarzania:

```text
python manage.py verify_full_backup full-backups/NAZWA.saas --from-storage --max-age-hours 30
python manage.py verify_full_backup /prywatny/katalog/kopia.saas --max-age-hours 30
```

Wiek jest liczony z uwierzytelnionego czasu snapshotu, a nie nazwy pliku lub
daty uploadu. Błędna/stara kopia daje niezerowy kod wyjścia; kontrola nie wraca
po cichu do starszej. Stary `check_backup` nie monitoruje nowego formatu.
Polecenie nie konfiguruje harmonogramu ani odbiorcy alarmów.

## Próba odtworzenia — nowa lokalna baza

1. Pobrać szyfrogram do prywatnego katalogu. Przygotować odizolowany proces
   bez produkcyjnego pliku `.env`, ustawiając `PYTHON_DOTENV_DISABLED=1` przed
   uruchomieniem Django. Używać wyłącznie lokalnej bazy i wyłączonych usług
   web/worker/beat. Nie przekazywać kluczy SMTP, Stripe, AI ani dostępu do R2
   procesowi odtwarzania.
2. Przygotować PostgreSQL z pgvector w tej samej głównej wersji co źródło
   (produkcja: 16), kod w wersji zapisanej w kopii oraz pustą bazę o nazwie
   `saas_restore_<identyfikator>`. Połączyć się przez localhost/127.0.0.1/::1.
   Uruchomić `migrate`. Nie wykonywać flush ani odtwarzania na istniejącej bazie.
3. Bezpiecznie dostarczyć kopie BACKUP_ENCRYPTION_KEY i oryginalnego
   DJANGO_SECRET_KEY. Właściciel już potwierdził ich zapis poza Renderem.
   Polecenie porównuje dowód zgodności drugiego klucza, nie drukując jego wartości.
4. Uruchomić z nowym, nieistniejącym katalogiem docelowym:

```text
python manage.py restore_full_backup /prywatny/kopia.saas --output /prywatny/nowe-odtworzenie
```

Polecenie odmawia pracy na Renderze, zdalnym adresie bazy, niezgodnej nazwie,
wersji PostgreSQL, wersji aplikacji, migracjach lub kluczu Django. Odrzuca bazę
z danymi aplikacji. Przed importem ponownie sprawdza pusty cel pod blokadami tabel
(NOWAIT), więc równoczesny zapis nie zostanie nadpisany. Błąd importu, liczby
rekordów lub powiązań plików wycofuje transakcję danych.

W procesie próby magazyny wskazują na rozpakowane lokalne pliki, e-mail korzysta
z dummy backendu, zadania nie wykonują się inline, a broker wskazuje na pamięć.
Połączenia i DNS przez Python socket są ograniczone do lokalnego portu bazy.
To dodatkowa blokada w procesie, nie zamiennik izolacji sieciowej środowiska ani
uprawnień systemowych. Polecenie nie uruchamia serwera ani workera.

5. Wynik rozpakowania: `database.json`, `restore-manifest.json`, `public/` oraz
   `private_documents/`. Ustawienia magazynów obowiązują tylko w procesie próby.
   Jeśli uruchamiany jest później izolowany panel/API do odbioru, jawnie skierować
   magazyny na te katalogi; nie używać produkcyjnej konfiguracji R2. Nie uruchamiać
   odtworzonej kolejki powiadomień ani procesów integracyjnych.
6. Sprawdzić na syntetycznej firmie login/MFA, role, odmowy między firmami,
   pobieranie plików, treść i wektory wiedzy. Dla rzeczywistej kopii sprawdzić
   uprawnione próbki bez wysyłania wiadomości, płatności lub zapytań AI.
7. Zapisać czas snapshotu, czas pobrania, weryfikacji, przygotowania środowiska,
   odtwarzania i odbioru. Czas wypisany przez komendę obejmuje wyłącznie jej proces;
   nie jest pełnym RTO. RPO wynika z wieku ostatniej zweryfikowanej kopii, a nie
   z samego powodzenia testu. Uzgodnić cele z właścicielem i porównać z pomiarem.
8. Po zapisaniu wyniku usunąć tylko wyraźnie oznaczoną testową bazę i prywatny
   katalog próby. Nie usuwać źródła, starych kopii ani kluczy. Przy awarii dysku
   może zostać częściowy katalog; nie jest oznaczany jako zakończony restore.

Samo `unpack_full_backup ... --output ...` weryfikuje i rozpakowuje dane, ale
nie dotyka bazy. Nie stanowi samodzielnie dowodu udanego odtworzenia aplikacji.

## Wdrożenie, rollback i pozostały odbiór

Wdrożyć backend/web i worker 2.0.14. Brak migracji, nowych zależności, sekretów,
usług oraz zmian panelu. CI używa bazy `saas_restore_ci`, aby pełna próba przechodziła
te same ograniczenia nazwy celu co narzędzie operatora.

Rollback kodu do 2.0.13 nie zmienia danych ani plików. Zachować archiwa obu
formatów i kod 2.0.14 potrzebny do ich sprawdzenia/odtwarzania. Nie zmieniać
klucza ani nie usuwać wcześniejszych kopii w ramach rollbacku.

Warunek zamknięcia F04/F21: rzeczywista kompletna kopia i jej izolowany restore
na PostgreSQL 16, zmierzone RPO/RTO, sprawdzony harmonogram oraz odbiór alarmów,
w tym braku przebiegu. Zielony CI na danych syntetycznych nie zamyka tych punktów.
