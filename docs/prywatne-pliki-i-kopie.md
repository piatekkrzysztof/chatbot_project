# Prywatne dokumenty i zaszyfrowane kopie

## Stan sprawdzony 9 września 2026

Panel Render potwierdził wdrożenie commita `4ac315871eab5ca54d0747a62c3595a10b444490`
(PR #39) na web i workerze. Web ma ustawienia magazynu Cloudflare R2. Worker
nie ma zmiennych `AWS_*`; jego dostęp do istniejących plików wymaga konfiguracji.
Nie odczytywano kluczy dostępu i nie zmieniano konfiguracji produkcyjnej.
Nie sprawdzono polityk bucketów w panelu Cloudflare ani prywatności istniejących
obiektów. Obecny kod kierował dokumenty i jawne kopie do magazynu publicznego
brandingu. Samo scalenie tej poprawki nie usuwa już zapisanych kopii.

## Przed scaleniem i automatycznym wdrożeniem

1. Utwórz dwa prywatne buckety: jeden na dokumenty, drugi na szyfrowane kopie.
   Dotychczasowy bucket pozostaje dla logo. W prywatnych bucketach wyłącz
   publiczny adres `r2.dev` i domeny niestandardowe; nie przyznawaj publicznego
   odczytu. S3 wymaga odpowiednio Block Public Access i kontroli polityki/ACL.
   Potwierdź odmowę anonimowego pobrania syntetycznego pliku kontrolnego.
   [Obie drogi dostępu opisuje dokumentacja R2](https://developers.cloudflare.com/r2/buckets/public-buckets/).
2. Przygotuj poświadczenia ograniczone do właściwych bucketów. Zwykły dostęp do
   dokumentów nie powinien dawać dostępu do backupów. Nie umieszczaj ich w kodzie,
   opisie PR, logach ani rozmowie.
3. Ustaw `DOCUMENTS_STORAGE_BUCKET_NAME`, `DOCUMENTS_ACCESS_KEY_ID`,
   `DOCUMENTS_SECRET_ACCESS_KEY`, `DOCUMENTS_S3_ENDPOINT_URL` oraz
   `DOCUMENTS_S3_REGION_NAME` na **web i workerze**. Dla R2 endpoint pochodzi z
   panelu Cloudflare, a region to `auto`. W AWS podaj rzeczywisty region.
   Web zapisuje i odczytuje dokumenty; worker potrzebuje odczytu plików.
4. Na usłudze wykonującej backup i migrację ustaw analogiczne `BACKUPS_*` oraz
   `BACKUP_ENCRYPTION_KEY`. Zwykły worker nie potrzebuje dostępu do kopii.
   Klucz Fernet wygeneruj na zaufanej maszynie poleceniem poniżej i zachowaj
   również w menedżerze sekretów poza Renderem. Nie używaj klucza Django.
5. Do czasu migracji worker potrzebuje również dostępu do **starego** magazynu:
   ustaw tam `AWS_STORAGE_BUCKET_NAME`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
   `AWS_S3_ENDPOINT_URL`, `AWS_S3_REGION_NAME` zgodnie z magazynem web. Po migracji
   można odebrać workerowi te uprawnienia. Logo na web zachowuje publiczną domenę.
6. Dopiero po ustawieniu konfiguracji scal PR i sprawdź wdrożenie tego samego
   commita na obu usługach. Bez `DOCUMENTS_*` nowy upload zwróci 503; bez klucza
   szyfrowania komenda backupu odmówi pracy. Nie ma publicznego fallbacku.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Klucza nie można odzyskać z aplikacji ani backupu. Przy rotacji zachowaj stary
klucz do odczytu starych kopii; najpierw sprawdź odtworzenie z nowym kluczem.

## Migracja istniejących obiektów

Wykonuje ją operator z dostępem do starego oraz obu nowych magazynów.
Najpierw zatrzymaj stare procesy zapisujące pliki oraz harmonogram jawnych
backupów. Pracuj w oknie obsługowym; nie uruchamiaj dwóch migracji równocześnie.
Przed usunięciem źródeł potwierdź polityki dostępu do celów i odzyskiwanie danych.

```bash
# Inwentaryzacja: tylko odczyt, bez kopiowania i usuwania.
python manage.py migrate_private_files

# Kopiowanie i kontrola zawartości. Stare obiekty pozostają dostępne.
python manage.py migrate_private_files --apply

# Po sprawdzeniu prywatności celów, pobierania i odtworzenia backupu:
python manage.py migrate_private_files --apply --delete-source
```

Dokumenty zachowują klucze zapisane w bazie. Komenda porównuje SHA-256 źródła
i celu, a istniejącego odmiennego celu nie nadpisuje. Backup JSON jest szyfrowany
przed wysłaniem, następnie odszyfrowywany i porównywany z oryginałem. Usunięcie
źródła następuje tylko po sprawdzeniu zgodności. Po błędzie można ponowić
komendę. Wartość `--kind documents` lub `--kind backups` ogranicza zakres.

Po zakończeniu ustaw `ALLOW_LEGACY_DOCUMENT_READS=false` na obu usługach.
W razie błędu konfiguracji lub braku dokumentu nie zostanie użyty stary magazyn.
Sprawdź ponownie anonimowe stare URL-e. W Cloudflare usuń również wersje
historyczne, cache CDN i inne publiczne kopie, jeżeli istnieją. Samo usunięcie
bieżącego obiektu nie dowodzi usunięcia cache lub historycznej wersji.

Migracja dokumentów obejmuje pliki wskazywane przez rekordy `Document`, a kopii
— pliki `.json` pod `backups/` starego magazynu. Nie usuwa osieroconych uploadów,
kopii w innych prefiksach, lokalnych plików z katalogu `backups/` ani wersji
historycznych. Zinwentaryzuj je osobno; nie kasuj jedynej działającej kopii.
Dotychczasowe pliki lokalne można przenieść do chronionego archiwum; nowy backup
wykonuje się już z szyfrowaniem. Nowy zapis dokumentów używa losowej nazwy w
`private-documents/<firma>/`, bez pierwotnej nazwy pliku.

## Nowe kopie i odtwarzanie

```bash
# Wyłącznie zaszyfrowany obiekt zdalny; bez lokalnego pliku.
python manage.py backup_data --to-storage

# Opcjonalna zaszyfrowana kopia na zaufanym dysku, poza MEDIA_ROOT.
python manage.py backup_data --output /secure/nowa-kopia.json.fernet

# Po pobraniu kopii do zaufanej maszyny i wskazaniu właściwego klucza:
python manage.py decrypt_backup /secure/nowa-kopia.json.fernet --output /secure/restore.json
```

Odszyfrowany JSON zawiera dane i sekrety bazy. Pliki lokalne powstają z prawami
0600 na systemach POSIX, bez nadpisywania istniejących plików; na Windows należy
również zapewnić odpowiednie ACL katalogu. Po odszyfrowaniu postępuj zgodnie z
[procedurą odtworzenia](odtwarzanie-z-kopii.md), a JSON usuń po zakończeniu próby.
Nigdy nie wczytuj go do zajętej bazy. `decrypt_backup` sam nie zmienia bazy.

Format korzysta z Fernet biblioteki PyCA cryptography, z uwierzytelnieniem
szyfrogramu. Uszkodzony plik albo błędny klucz nie tworzy pliku wynikowego.
Limit zrzutu to 100 MiB danych jawnych ze względu na przetwarzanie w pamięci.
Dla większej bazy potrzebna jest procedura PostgreSQL ze strumieniowym
szyfrowaniem. Zrzut Django nie zastępuje spójnej kopii PostgreSQL/PITR i nie
obejmuje bajtów uploadów — osobno zapewnij wersjonowanie/backup prywatnych plików.

## Warunki zamknięcia F04

Od 2.0.1 zdalna kopia jest odczytywana i porównywana po zapisie. Polecenie
`check_backup` sprawdza integralność i wiek ostatniej kopii. Konfigurację
osobnych zadań i odbiór alarmów opisuje
[harmonogram i kontrola kopii](harmonogram-i-kontrola-kopii.md).

- Dwa prywatne buckety nie pozwalają na anonimowe pobranie ani listowanie.
- Użytkownik A pobiera własny plik; użytkownik B i publiczny klucz widgetu nie.
- Nowy upload oraz zadanie przetwarzające działają na web i workerze.
- Istniejące pliki przeniesiono, publiczne kopie i cache zinwentaryzowano/usunięto.
- Wyłączono odczyt starego magazynu; logo widgetu nadal działa.
- Zaszyfrowaną kopię odtworzono w osobnej bazie, razem z danymi i embeddingami.
- Harmonogram i alarmy działają; ustalono PostgreSQL/PITR, kopie bajtów plików
  oraz RPO/RTO potwierdzone pełnym odtworzeniem na stagingu.
- `python manage.py check --deploy` nie zgłasza brakującej konfiguracji prywatnych
  magazynów na właściwej usłudze. Sama kontrola ustawień nie sprawdza ACL w chmurze.

Źródła: [konfiguracja django-storages](https://django-storages.readthedocs.io/en/1.14.6/backends/amazon-S3.html),
[Fernet](https://cryptography.io/en/latest/fernet/).
