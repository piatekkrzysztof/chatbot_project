# Harmonogram, kontrola kopii i odbiór odtwarzania

Wydanie 2.0.1. Ten dokument i przykładowy Blueprint przygotowują konfigurację;
nie potwierdzają uruchomienia zadań ani dostarczenia alarmów na produkcji.

## Kontrakt poleceń

`python manage.py backup_data --to-storage` wykonuje zrzut danych aplikacji,
szyfruje go niezależnym `BACKUP_ENCRYPTION_KEY`, zapisuje pod unikalną nazwą
w `private_backups` i porównuje odczytane bajty z wysłanym szyfrogramem.
Sukces następuje dopiero po porównaniu. Awaria zapisu/odczytu lub niezgodne bajty
kończą proces błędem. Nieudana weryfikacja nie usuwa zdalnego obiektu; operator
może go zbadać, a ponowienie zapisze nową nazwę. Stare kopie nie są nadpisywane.

`python manage.py check_backup --max-age-hours 30`:

- wymaga prywatnego magazynu kopii, odczytu/listowania oraz właściwego klucza;
- wybiera najnowszą nazwę `backups/kopia-YYYYMMDD-HHMMSS-<uuid>.json.fernet`;
- odczytuje plik z limitem pamięci, sprawdza uwierzytelnione szyfrowanie,
  niepusty JSON i czas powstania zapisany w podpisanym tokenie Fernet;
- odrzuca wiek ponad próg i czas ponad 60 sekund w przyszłości; nie ufa dacie
  ostatniego uploadu ani świeżo zmienionej nazwie starego pliku;
- przy uszkodzonej najnowszej kopii zgłasza błąd zamiast wybierać starszą;
- zwraca kod 0 oraz JSON `status`, `created_at` (Unix UTC), `age_seconds`,
  `objects`; przy błędzie kończy się niezerowym kodem, bez treści zrzutu;
- nie zapisuje plików, nie zmienia bazy i nie wykonuje połączeń z bazą.

Kontrola nie dowodzi kompletności danych ani odtwarzalności schematu. Stare
migrowane kopie o innej nazwie nie są dowodem działania nowego harmonogramu.
Lista nazw jest obecnie pobierana w całości; należy ustalić retencję i obserwować
czas listowania przy rosnącym archiwum. Polecenia same nie usuwają żadnych kopii.

## Wdrożenie po scaleniu PR

1. Sprawdź wersję kodu oraz działanie obecnych magazynów. Zachowaj istniejący
   klucz szyfrowania i jego kopię poza hostingiem; nie generuj nowego klucza
   zamiast tego, który jest potrzebny do odczytu historycznych kopii.
2. Utwórz osobne zadanie kopii z repozytorium backendu i gałęzi `main`.
   [Blueprint](render-backups.example.yaml) jest oddzielny od głównego
   `render.yaml`: jego użycie wymaga świadomego utworzenia usług. Dopasuj region
   do bazy i plan pamięci do pomiaru kopii. Są to dodatkowo rozliczane zadania.
3. Harmonogram początkowy: raz dziennie o 03:00 UTC, `0 3 * * *`.
   Build: `pip install -r requirements.txt`. Command:
   `python manage.py backup_data --to-storage`. Build nie wykonuje migracji
   ani tworzenia kopii. Render interpretuje harmonogram w
   [UTC](https://render.com/docs/cronjobs).
4. Zadaniu kopii przekaż tylko ustawienia z przykładu: URL właściwej bazy
   (preferowany osobny użytkownik tylko do odczytu wszystkich wymaganych tabel),
   `BACKUPS_*` i istniejący klucz szyfrowania. Nowy `DJANGO_SECRET_KEY` może być
   osobny: komenda nie obsługuje sesji panelu. Nie przekazuj Stripe, OpenAI,
   poczty, Redis ani poświadczeń dokumentów/publicznych logo.
5. Utwórz niezależne zadanie kontroli co godzinę, `15 * * * *`, z komendą
   `python manage.py check_backup --max-age-hours 30`. Użyj osobnego tokenu R2
   tylko do odczytu/listowania bucketa kopii. Potrzebuje klucza szyfrowania,
   ale nie produkcyjnego URL bazy. Przykład zawiera nieużywany adres lokalny.
   Nie dodawaj uprawnień kopii do workera przetwarzającego dokumenty.
6. Dla obu zadań włącz dostarczanie powiadomień o błędach do operatora.
   [Render obsługuje alarmy błędów cron](https://render.com/docs/notifications).
   Zapisanie konfiguracji nie dowodzi ich dostarczenia. Na syntetycznym
   środowisku wywołaj błąd i potwierdź odebranie alarmu.
7. Uruchom kopię raz ręcznie, następnie kontrolę. Zweryfikuj obiekt w prywatnym
   magazynie i wynik obu poleceń. Sprawdź również pierwszy automatyczny przebieg.
   Zapisz datę, commit, czas, liczbę obiektów i wielkość bez danych klientów.

Próg 30 godzin daje zapas po dziennym przebiegu; nie jest gwarancją RPO 24 h.
Sama kontrola uruchamiana na Renderze nie wykryje awarii całego Rendera lub
zatrzymania obu harmonogramów. Do odbioru komercyjnego potrzebny jest niezależny
monitor braku przebiegów, poza tym hostingiem, z przetestowanym alarmem.

## Odtwarzanie na stagingu

1. Przygotuj pustą, izolowaną bazę PostgreSQL z pgvector i kod zgodny ze schematem
   kopii. Nie kieruj poleceń do produkcyjnej bazy ani do zajętego stagingu.
2. Odłącz ruch, kolejki i integracje płatnicze/pocztowe/AI. Na stagingu zablokuj
   połączenia wychodzące do tych usług. Użyj syntetycznych danych w próbie CI;
   rzeczywistą kopię odtwarzaj wyłącznie w uzgodnionym, chronionym środowisku.
3. Pobierz wybraną zaszyfrowaną kopię; zweryfikuj klucz, odszyfruj do nowego
   chronionego pliku przez `decrypt_backup`, uruchom `migrate`, potem `loaddata`.
   Szczegóły i ograniczenia: [instrukcja odtwarzania](odtwarzanie-z-kopii.md).
4. Porównaj liczby i relacje, tożsamości kluczy widgetu, hasła, wektory oraz
   działanie logowania i autoryzacji. Osobno odtwórz bajty plików i sprawdź
   pobieranie własnego dokumentu oraz odmowę dostępu z innej firmy.
5. Zmierz RTO od rozpoczęcia odbudowy do działającej aplikacji oraz RPO na
   podstawie wybranej kopii. Zanotuj wynik, ograniczenia i wykryte problemy.
   Usuń tylko tymczasowe dane próby po potwierdzeniu jej zakresu.

Test `accounts/tests/test_remote_backup_restore.py` pokrywa zrzut, szyfrowanie,
kontrolę magazynu, odszyfrowanie, utratę testowej bazy i odtworzenie relacji,
kluczy, haseł i wektorów bez zlecania przetwarzania. Magazyn S3 jest w nim atrapą.
Nie zastępuje to pełnej próby odtworzenia produkcji na stagingu.

## Otwarte warunki odbioru

- Działający harmonogram i potwierdzone powiadomienia, w tym brak przebiegów.
- Backup PostgreSQL/PITR oraz ustalone RPO/RTO. Zrzut Django jest kopią logiczną
  aplikacji, pomija wybrane tabele i nie zapewnia jednej transakcyjnej migawki
  przy równoległych zmianach. Nie zastępuje kopii PostgreSQL.
- Niezależne kopie bajtów uploadów, polityka retencji i dostęp do starszych
  kluczy szyfrowania. Ten PR nie dodaje automatycznego kasowania archiwum.
- Pełny test odtworzenia na stagingu i regularne ponawianie tej próby.
