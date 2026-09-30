# A04 — trwałe usuwanie plików

Wersja 2.19.4, 30.09.2026. Poprawka przygotowana do przeglądu i wdrożenia.
Testy lokalne i CI nie są potwierdzeniem konfiguracji ani odbioru produkcji.

## Problem i zakres

Dotychczas po zatwierdzeniu usunięcia rekordu wykonywaliśmy callback kasujący
plik. Awaria procesu pomiędzy zatwierdzeniem a callbackiem albo błąd magazynu
pozostawiał obiekt bez trwałej informacji, że należy go usunąć.
Przy wymianie logo w autocommit callback mógł też skasować poprzedni plik
przed nieudanym zapisem nowej wartości do bazy.

Teraz usunięcie dokumentu, kaskada usunięcia firmy oraz wymiana dokumentu,
logo lub awatara zapisują zlecenie w tej samej transakcji co zmiana danych.
Nieudany zapis zlecenia wycofuje zmianę właściciela pliku. Brak pliku
w rekordzie nie tworzy pustego zlecenia. Zapis niezwiązanych ustawień
z użyciem update_fields nie dodaje zapytań dotyczących plików.

Rejestr UsunieciePliku nie ma klucza obcego do firmy: musi przeżyć jej usunięcie.
Przechowuje techniczny identyfikator firmy, alias magazynu, skrót tożsamości
magazynu, nazwę obiektu, stan, próby i czasy. Nie zapisuje kluczy dostępu.
Nazwa starego obiektu może zawierać dane osobowe; rejestr jest wewnętrzny
i nie jest wystawiony w API klienta.

## Wykonanie i zabezpieczenia

1. Po zatwierdzeniu transakcji próbujemy obudzić istniejący worker.
   Błąd brokera nie usuwa zlecenia i nie powoduje synchronicznego kasowania.
2. Beat co minutę wybiera najwyżej 50 gotowych zleceń. Budżet pętli to
   60 sekund sprawdzane między obiektami; pojedynczy wolny obiekt może go
   przekroczyć. Limit całego zadania to 110/120 sekund (miękki/twardy).
3. Worker zajmuje wiersz krótką blokadą, zapisuje token i dzierżawę na
   10 minut, a dopiero po zatwierdzeniu kontaktuje się z magazynem.
   Zadanie pojedynczego obiektu ma limit 50/60 sekund. Klient S3 kasujący
   pliki ma osobne timeouty połączenia 5 s i odczytu 10 s oraz jedno ponowienie
   SDK; konfiguracja uploadów pozostaje bez zmian.
4. Worker sprawdza nazwę, zgodność magazynu i odwołania do pliku wszystkich
   firm. Plik nadal używany pozostaje na miejscu, a zlecenie otrzymuje stan
   zachowany. Usunięcie ostatniego odwołania tworzy kolejne zlecenie.
5. Kasowanie jest powtarzalne: brak obiektu oznacza wykonanie. Awaria po
   usunięciu bajtów, a przed zapisem potwierdzenia, nie gubi zlecenia.
   Token nie pozwala starej próbie potwierdzić pracy nowszego workera.
   Nie obiecujemy dokładnie jednego wywołania magazynu.
6. Błędy magazynu ponawiamy maksymalnie 8 razy. Odstępy wynoszą 1, 2, 4,
   8, 16, 32 i 60 minut, plus oczekiwanie na wolnego workera. Przerwany
   proces można odzyskać po dzierżawie. Po wyczerpaniu prób wymagana jest
   interwencja operatora; zlecenie nie znika.
7. Nowe pliki brandingu otrzymują losową nazwę również przy zapisie przez
   model/admin. Równoległe wymiany blokują ten sam rekord i każda zachowuje
   zlecenie dla faktycznie zastąpionej wersji. Dokumenty już używają losowych nazw.
8. Zmiana bucketa, endpointu, regionu, prefiksu S3 albo katalogu lokalnego
   blokuje stare zlecenie. Sama rotacja kluczy dostępu nie zmienia jego celu.
   Nieobsługiwany backend jest odrzucany. Tryb migracji starych dokumentów
   z ALLOW_LEGACY_DOCUMENT_READS=True tworzy osobne zlecenia dla prywatnego
   i publicznego magazynu; nowe private-documents/* dotyczą tylko prywatnego.

## Stany, alarm i retencja rejestru

| Stan | Znaczenie i reakcja |
|---|---|
| oczekuje | Czeka na worker lub termin ponowienia |
| praca | Próba zajęta; po 10 minutach bez zakończenia można ją odzyskać |
| gotowe | Magazyn potwierdził kasowanie albo brak obiektu |
| zachowany | Istnieje żywe odwołanie; plik celowo pozostaje |
| blad | Zabezpieczenie zablokowało kasowanie lub wyczerpano próby |
| wstrzymane | Zlecenie odtworzono z kopii; automatyczne wykonanie wyłączone |

Stan blad albo niezakończone zlecenie starsze niż 15 minut kwalifikuje się
do alarmu na istniejący EMAIL_ALERTOW (fallback DEFAULT_FROM_EMAIL).
Partia obejmuje najwyżej 50 zleceń; każde może alarmować raz na godzinę.
E-mail i log zawierają identyfikator oraz bezpieczny kod, bez nazw obiektów,
sekretów i surowych odpowiedzi dostawcy. Błąd wysyłki umożliwia ponowienie.
Jeśli proces zginie po zajęciu alarmu, ponowna wysyłka może czekać godzinę.
Sukces SMTP wymaga osobnego potwierdzenia dotarcia wiadomości.

Zakończone wpisy gotowe/zachowany sprzątamy po 30 dniach, do 200 na przebieg.
Niezakończone, zablokowane i wstrzymane wpisy nie wygasają automatycznie.
Nie zmieniamy okresów przechowywania dokumentów klientów ani archiwum kopii.

Zatrzymany worker lub Beat nie wyśle własnego alarmu. Ich działanie wymaga
odrębnego nadzoru. Poniższy raport może być wywoływany przez istniejący
monitor operacyjny; A04 nie tworzy nowej płatnej usługi monitorującej.

## Kontrola operatora

Odczyt bazy, bez kasowania, nazw plików i kontaktu z magazynem:

```text
python manage.py kontrola_usuwania_plikow
python manage.py kontrola_usuwania_plikow --magazyny
```

Pierwsza komenda liczy wszystkie niezakończone zlecenia i wypisuje do 100.
Kod zakończenia jest niezerowy przy zablokowanym lub zaległym zleceniu.
Druga wypisuje wyłącznie aliasy i skróty celu — porównać osobno na web
i workerze. Zgodność skrótów nie dowodzi uprawnień do kasowania w R2.

1. Przy oczekuje/praca sprawdzić działanie workera i Beat, wiek zlecenia
   oraz zaległość kolejki. Nie resetować aktywnej próby.
2. Przy brak_uprawnien/brak_bucketa sprawdzić konfigurację i zakres tokena
   właściwego magazynu. Przy blad_magazynu sprawdzić dostępność dostawcy.
3. Przy zmieniony_magazyn porównać konfigurację z miejscem utworzenia
   zlecenia. Przywrócić prawidłowy cel albo przygotować odrębną kontrolowaną
   migrację. Nie przepisywać automatycznie skrótu w bazie.
4. Przy nieprawidlowa_nazwa zbadać źródłowy rekord; nie omijać walidacji.
5. Po usunięciu przyczyny operator może jawnie zresetować jedno zlecenie:

```text
python manage.py kontrola_usuwania_plikow --ponow 123
```

Komenda nie usuwa pliku: oddaje zlecenie kolejnemu przebiegowi. Sprawdza
cel i odwołania, odrzuca zakończoną lub aktywną próbę. Następnie należy
potwierdzić wynik w bazie i rzeczywisty brak testowego obiektu w magazynie.

## Kopie i odtwarzanie

Rejestr wchodzi do pełnej kopii bazy. restore_full_backup nadal wymaga
pustej lokalnej bazy — same zlecenia usunięcia również blokują odtwarzanie.
Po sprawdzeniu liczby rekordów i powiązań plików, w tej samej transakcji,
komenda zmienia wszystkie niezakończone zlecenia na wstrzymane.
Nie usuwa ich z kopii ani nie wykonuje ich przeciw źródłowemu magazynowi.

Nie należy wznawiać tych zleceń podczas ćwiczenia restore. Ewentualne
odtworzenie usługi i wznowienie pracy wymagają osobnej kontroli celu
magazynów oraz decyzji o każdym zleceniu. Bezpośrednie loaddata i surowy
import SQL nie zastępują zabezpieczonej komendy restore_full_backup.

## Wdrożenie i odbiór krok po kroku

1. Odebrać CI dla konkretnego commita; zachować poprzedni commit i sprawną
   pełną kopię. Nie prowadzić równolegle migracji magazynów.
2. Porównać konfigurację web/workera: baza, prywatny magazyn dokumentów,
   publiczny branding, broker oraz adres alarmów. Bez wklejania kluczy do logów.
3. Na czas przełączenia wstrzymać operacje wymiany/usuwania plików oraz
   usuwania firm; poczekać na zakończenie starych żądań i takich zadań.
   Stary kod nadal może utracić zlecenie, więc mieszana wersja nie zapewnia A04.
4. Wykonać migracje documents.0016_trwale_usuwanie_plikow i
   accounts.0044_trwale_usuwanie_plikow przed uruchomieniem nowych procesów.
   Pierwsza tworzy rejestr, druga zmienia sposób nazywania nowych obrazów.
   Istniejące pliki nie są przenoszone ani masowo usuwane przez migracje.
5. Uruchomić web i worker/Beat z tego samego commita; sprawdzić /health/
   2.19.4, obecność obu zadań usuwania i pierwszy przebieg okresowy.
   Porównać wynik --magazyny na obu usługach. Wznowić operacje po kontroli.
6. Na wydzielonej firmie i wyłącznie testowych plikach sprawdzić: dokument,
   wymianę logo i awatara, wspólny obraz obu pól, usunięcie firmy oraz
   zachowanie pliku innej firmy. Potwierdzić rekord zlecenia i bajty w R2.
7. W izolowanym środowisku testowym sprawdzić niedostępny magazyn,
   odzyskanie po utracie callbacku, przerwanym workerze i niedostępnym brokerze.
   Nie wyłączać dostępu do produkcyjnego bucketa w celu symulacji.
8. Odebrać testowy alarm w skrzynce, sprawdzić raport i skuteczne ponowienie
   po naprawie przyczyny. Potwierdzić niezależny nadzór nad workerem.
9. Wykonać pełną kopię i izolowane odtworzenie zgodną wersją; potwierdzić,
   że niedokończone zlecenia są wstrzymane. Nie uruchamiać ich ręcznie.
10. Zapisać commit, czas wdrożenia, wyniki i odbiorcę alarmu w protokole.
    Dopiero wtedy oznaczyć A04 jako wdrożone i odebrane.

Rollback: wstrzymać operacje zmiany/usuwania plików i zanotować zaległe
zlecenia. Nie cofać migracji usuwającej tabelę z niewykonanymi zleceniami.
Powrót starego web/workera przywraca ryzyko A04 i nie opróżnia rejestru.
Najbezpieczniej poprawić nową wersję i wznowić zachowane zlecenia; każda
próba utrzymania nowego workera przy starszym web wymaga kontroli zgodności.

## Granice poprawki i dalsze kroki

- A04 nie odszukuje historycznych sierot ani uploadów, których zapis do bazy
  nigdy się nie udał. Następny krok to raport obiektów bez odwołania,
  z uwzględnieniem oczekujących zleceń i trwających uploadów; bez kasowania.
- Raw SQL, QuerySet.update i bulk_update pól plikowych omijają sygnały.
  Zmiany plików należy wykonywać przez zapis modelu z tym protokołem.
  Nazw dawnych usuniętych obiektów nie wolno ponownie przypisywać.
- Potwierdzenie usunięcia dotyczy bieżącego obiektu. Wersjonowanie R2/S3,
  kopie, CDN i polityki dostawcy wymagają osobnego odbioru infrastruktury.
- Odbiory A01/A02 i A03/A05, końcowy test obciążenia oraz pozostałe bramki
  odbioru komercyjnego zachowują status z roadmapy; A04 ich nie zamyka.


## Dodatkowa blokada wykryta przez CI

Pierwszy skan obrazu dla A04 zgłosił CVE-2026-75804 i CVE-2026-84782
w trzech pakietach OpenSSL (sześć trafień HIGH). Obraz bazowy zawierał
3.5.7-1~deb13u2, podczas gdy repozytorium bezpieczeństwa Debiana udostępniało
3.5.7-1~deb13u3. Dockerfile wykonuje teraz aktualizację pakietów systemowych.
Nie dodano wyjątków skanera. Przy kolejnej poprawce systemowej i trafieniu
w cache trzeba przebudować obraz z --pull --no-cache; samo ponowne
uruchomienie tego samego zbuforowanego kroku nie odświeża pakietów.

Źródło wersji: [Debian Security Tracker — OpenSSL](https://security-tracker.debian.org/tracker/source-package/openssl).
