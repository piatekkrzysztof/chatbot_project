# Raport plików bez odwołania — 2.19.5

Narzędzie operatora po A04. Czyta wyłącznie metadane magazynu i rekordy bazy.
Nie pobiera treści plików, nie kasuje obiektów, nie modyfikuje danych i nie
tworzy zleceń usuwania. Nie ma opcji apply/delete ani automatycznego harmonogramu.

Kontrola z 17.09.2026 nie wykazała sierot. To historyczny wynik, który pozostaje
w F18. Nowa komenda pozwala powtórzyć kontrolę po kolejnych uploadach lub awarii;
jej dodanie nie oznacza wykrycia wycieku ani ponownego otwarcia dawnego odbioru.

## Zakres

Wybrać jeden magazyn na przebieg:

| Alias | Sprawdzane prefiksy względne |
|---|---|
| private_documents | private-documents/ oraz historyczne documents/ |
| default | widget_branding/ oraz historyczne documents/ |

Prefiks location skonfigurowany w S3 jest uwzględniany. Komenda nie listuje
prywatnych kopii ani innych katalogów/bucketów. Pełny wynik oznacza pełne
przejście wskazanych prefiksów, **nie inwentaryzację całego bucketa**.
Obiekty w innych prefiksach, historyczne wersje S3/R2, nieukończone uploady
wieloczęściowe i cache CDN wymagają osobnych kontroli.

## Uruchomienie i odczyt

Najpierw wdrożyć A04 (2.19.4), w tym jego migracje. Wydanie 2.19.5 nie dodaje
migracji, sekretów, usług ani zmian frontendu. Uruchomić na zgodnej bazie
i konfiguracji magazynów; można użyć istniejącej powłoki operatora.

```text
python manage.py raport_plikow --magazyn private_documents
python manage.py raport_plikow --magazyn default
```

Wynik jest JSON-em. Zawiera alias, skrót celu zgodny z A04, zakres prefiksów,
czas rozpoczęcia/zakończenia, liczby obiektów i bajtów w każdej kategorii
oraz ograniczoną próbkę plików bez widocznego odwołania. Domyślnie próbka
zawiera SHA-256 identyfikatora obiektu zamiast jego nazwy.
Skrót jest pseudonimem, nie szyfrowaniem ani dowodem anonimizacji.

| Kategoria | Jak ją interpretować |
|---|---|
| powiazany | Baza nadal odwołuje się do pliku; uwzględniono wszystkie firmy |
| zlecenie_usuniecia | Istnieje niezakończone zlecenie A04 dla tego celu, również zablokowane lub wstrzymane |
| zlecenie_inny_cel | Nazwa występuje w zleceniu tego aliasu, ale cel magazynu się różni; sprawdzić konfigurację |
| zlecenie_zakonczone | Zakończony wpis A04, lecz obiekt nadal jest widoczny; wyjaśnić, nie kasować automatycznie |
| swiezy | Brak widocznego odwołania, ale obiekt jest młodszy od progu; możliwy upload przed zapisem rekordu |
| do_weryfikacji | Starszy obiekt bez widocznego odwołania i zlecenia; kandydat do sprawdzenia |
| niepewne_metadane | Brakuje wiarygodnego czasu/rozmiaru; nie uznajemy obiektu za sierotę |
| pominiety_specjalny | Symlink, inny specjalny wpis albo znacznik katalogu S3; nie śledzimy celu |

Odwołania do historycznych dokumentów sprawdzamy konserwatywnie w obu
magazynach, niezależnie od bieżącego ALLOW_LEGACY_DOCUMENT_READS. Może to
zachować kopię migracyjną jako powiązaną — raport nie potwierdza identycznej
treści duplikatów. Wspólne logo i awatar liczą się jako jeden obiekt magazynu.

## Limity i błędy

```text
python manage.py raport_plikow --magazyn private_documents --limit 10000 --sekundy 60 --wiek 24 --probka 100
```

- limit: 1–100000, domyślnie 10000 sklasyfikowanych obiektów.
- sekundy: 1–300, domyślnie 60. Budżet współpracujący sprawdzany między
  operacjami; nie przerywa już trwającego zapytania SQL ani żądania sieciowego.
- wiek: 1–8760 godzin, domyślnie 24. To próg diagnostyczny, nie retencja
  klienta ani gwarancja zakończenia wszystkich uploadów.
- probka: 0–1000, domyślnie 100. Ogranicza listę, nie liczniki.

S3 używa LIST w stronach po 250 wpisów, z timeoutami 5/10 sekund
(połączenie/odczyt) i jednym ponowieniem SDK. Nie wykonuje GET/HEAD obiektów.
Lokalny dysk jest przechodzony bez podążania za symlinkami, z ograniczeniem
głębokości 32 i liczby odwiedzonych wpisów. Zapytania bazy są wykonywane
partiami po 250 nazw. Raport zużywa operacje LIST i zapytania na obecnych
zasobach, ale nie wymaga nowej płatnej usługi.

Przekroczenie limitu albo błąd daje pelny_zakres_prefiksow=false, bezpieczny
kod i niezerowy kod zakończenia komendy. Częściowa partia może pozostać
niesklasyfikowana; jej wielkość jest jawna. Takiego wyniku nie wolno opisywać
jako „zero sierot”. Brak katalogu magazynu lokalnego również jest błędem.
Surowy wyjątek dostawcy z nazwami/adresami/sekretami nie trafia do raportu.

Skrót celu należy porównać z kontrola_usuwania_plikow --magazyny na web
i workerze. Sam zgodny skrót nie dowodzi kompletności danych ani uprawnień.
Token produkcyjny musi mieć uprawnienie LIST dla właściwego bucketa;
brak tego uprawnienia ma zatrzymać raport, nie oznaczać pustego magazynu.

## Jawne nazwy tylko dla operatora

```text
python manage.py raport_plikow --magazyn private_documents --nazwy --probka 100
```

Opcja nazwy dołącza klucze obiektów do próbki. Stare nazwy mogą zawierać dane
osobowe. Nie publikować wyniku w PR, publicznym logu ani czacie; przechowywać
go w prywatnym miejscu z dostępem operatora. JSON koduje znaki sterujące,
ale to nie usuwa wrażliwych danych. Nie ma masowego eksportu wszystkich nazw.

## Odbiór i następne kroki

1. Potwierdzić scalenie i wdrożenie A04 oraz zgodną wersję 2.19.5.
2. W środowisku testowym utworzyć plik używany, świeży upload, stary plik bez
   rekordu, wspólny obraz oraz zlecenie usunięcia. Potwierdzić kategorie
   i brak jakichkolwiek zmian w danych/pliku.
3. Sprawdzić brak uprawnienia LIST, limit czasu i limit obiektów: wszystkie
   mają dać niepełny wynik, nie potwierdzenie porządku w magazynie.
4. Na właściwym środowisku wykonać oba raporty bez opcji nazwy. Zapisać
   czas, wersję, skróty celów, zakres, liczniki i kompletność wyniku.
5. Jeśli wynik jest niepełny, wyjaśnić przyczynę i powtórzyć kontrolę
   w dopuszczalnych granicach. Większy magazyn wymaga osobno zaplanowanego
   eksportu inwentarza; ta komenda nie obiecuje wznowienia od kursora.
6. Zlecenia A04 rozpatrywać przez jego raport i procedurę ponowień.
   Kandydatów do_weryfikacji sprawdzić ponownie po zakończeniu zapisów,
   z aktualnymi odwołaniami i kopiami, przed jakąkolwiek decyzją o usunięciu.
7. Ewentualne usuwanie historycznych plików wymaga oddzielnego planu
   i uzgodnienia. Wynik tego raportu nigdy sam nie uprawnia do kasowania.

Skan działa na żywym magazynie i żywej bazie, bez wspólnej migawki. Równoległy
zapis lub usunięcie może zmienić klasyfikację w trakcie przebiegu; narzędzie
nie jest dowodem pełnej spójności ani braku aktywnego uploadu.
Przy przygotowaniu kodu nie uruchamiano inwentaryzacji produkcji.
Odbiór wykonano 30.09.2026 na 2.19.5: oba zakresy pełne, 1 powiązany dokument
(187 805 B), 0 obiektów default i 0 kandydatów do wyjaśnienia. Niczego nie
kasowano. [Zapis wyników](odbior-operacyjny-2026-10-01.md).

Rollback: wystarczy wrócić do kodu 2.19.4. Raport nie ma migracji, zadań
w tle ani zapisanych zmian wymagających odwrócenia.
