# Wgrywanie dokumentów, logo i awatara — F09

Wydanie 2.0.3 sprawdza plik przed zapisem do magazynu oraz przed zleceniem
embeddingów. Walidacja nie ufa nagłówkowi MIME podanemu przez przeglądarkę.
Prywatny magazyn dokumentów i publiczny magazyn brandingu nadal mają oddzielne role.

## Limity

| Wejście | Granica |
|---|---|
| Dokument | PDF, DOCX, TXT, MD; 10 MiB otrzymanych bajtów |
| Wyodrębniony tekst | 2 097 152 znaki; dodatkowo limit bazy wiedzy planu |
| PDF | 200 stron, bez szyfrowania; do 8 MiB rozpakowanego strumienia strony |
| DOCX | 256 elementów ZIP, 20 MiB po rozpakowaniu, 8 MiB na element |
| Logo/awatar | PNG, JPEG, WebP; 2 MiB, 4 mln pikseli, 4096 px na bok |
| Wynik obrazu | Statyczny PNG, do 1024 × 1024 px i 2 MiB; proporcje zachowane |
| Proces parsera | Do 192 MiB, 15 s CPU, 20 s czasu rzeczywistego dla dokumentu, 5 s dla obrazu |
| Współbieżność | Jeden parser na instancję aplikacji; kolejny otrzymuje 503 |

Wielkość pliku jest liczona podczas odbierania multipart. Duży Content-Length
odrzucamy przed odczytem. Zduplikowane i obce pola plikowe są odrzucane; przekroczenie
limitu usuwa tymczasowy plik. Limity te dotyczą dwóch endpointów uploadu, nie CSV.

TXT/MD wymagają UTF-8; dane binarne nie przechodzą. Pusty tekst jest odrzucany,
a skan PDF wymaga wcześniejszego OCR. DOCX nie rozpakowujemy na dysku, XML nie
może zawierać DTD/encji, a nazwy ze ścieżkami nadrzędnymi i makra VBA są odrzucane.
Obrazy dekodujemy i zapisujemy ponownie, usuwając EXIF, komentarze, profile i
doklejone dane. Zachowujemy kanał alfa i stosujemy orientację EXIF przed usunięciem metadanych.

## Proces i błędy

HTTP czeka na wynik ograniczonego procesu potomnego. Parser nie działa wewnątrz
Django ani w awaryjnym wykonaniu Celery w procesie API. Proces dostaje wyłącznie
bajty na stdin i zaufane argumenty programu; nie używamy powłoki. Nie dziedziczy
kluczy, ustawień Django, proxy ani PYTHONPATH. Limit pamięci na Linuksie dodatkowo
maleje do połowy dostępnego zapasu cgroup; mniej niż 96 MiB oznacza 503.

Linux używa limitów resource, Windows obiektu Job. Blokada plikowa obejmuje
procesy web/workera współdzielące instancję i katalog tymczasowy; blokada wątku
obejmuje także równoległe żądania w jednym procesie. Timeout zabija i odbiera
proces potomny. Niedostępne zabezpieczenia nie uruchamiają nieograniczonego fallbacku.

- 400: nieprawidłowy/nieobsługiwany plik, pusty tekst albo przekroczony czas.
- 413: przekroczony limit pliku lub wyodrębnionej zawartości.
- 503: zajęty parser, za mało pamięci albo nie można ustawić ochrony procesu.
- 201: dokument zapisany, tekst odczytany; sygnał zleca embeddingi jednokrotnie.

Pole API `processing_error` i status `failed` opisują błąd przetwarzania pliku
w tle, także pliku dodanego administracyjnie. Błąd nie zastępuje istniejącej
treści dokumentu. Szczegóły wyjątków dostawcy storage nie trafiają do API/logów.
Panel otrzymuje osobną poprawkę: formaty, limity, opisy statusów i zachowanie
wybranego pliku po odmowie serwera.

## Wdrożenie i odbiór

1. Najpierw scalić zależne poprawki kopii i pobierania stron: PR #41, następnie #42.
2. Uruchomić migracje, wdrożyć tę samą wersję backendu i workera. Migracja dodaje
   wyłącznie pole tekstowe z pustą wartością domyślną. Nie przenosi ani nie usuwa plików.
3. W staging sprawdzić zwykły PDF, polski DOCX/TXT, PNG z przezroczystością oraz
   JPEG z orientacją. Potwierdzić odczyt dokumentu i wygenerowane fragmenty.
4. Sprawdzić odmowę dla fałszywego PNG/PDF, SVG, pliku ponad limit i zajętego parsera.
   Potwierdzić brak zapisu i płatnych zadań przy odmowie oraz możliwość ponowienia.
5. Sprawdzić `/health/` (2.0.3), pamięć instancji, opóźnienia uploadu i odpowiedzi 503.
   Dopiero wynik na rzeczywistym rozmiarze instancji potwierdza odbiór operacyjny.

Cofnięcie kodu nie wymaga usuwania dodanego pola bazy. Oczyszczone PNG pozostają
zwykłymi obrazami obsługiwanymi przez wcześniejszy panel. Nowe reguły nie wykonują
retrospektywnego skanowania ani konwersji istniejących plików.

## Granice etapu

To izolacja zasobów parsera, a nie pełna piaskownica systemu plików i sieci.
Parser działa z uprawnieniami procesu usługi. Nie zastępuje aktualizacji bibliotek,
antywirusa/CDR ani niezależnej izolacji kontenera i reguł wyjścia sieciowego.
Limity per instancja nie zastępują limitów żądań i budżetów kosztów per firma (F08).
Proxy/WSGI może buforować ciało przed przekazaniem do Django; jego limit oraz
zużycie pamięci całej instancji wymagają odbioru infrastruktury.

Atomowość sumarycznego limitu wiedzy, retry/publikacja embeddingów i usuwanie
osieroconych plików po awarii storage pozostają w F10/F19. Jednoczesna walidacja
logo i awatara nie jest transakcją między bazą a magazynem obiektowym.

Polityka opiera się na [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
i ostrzeżeniu [pypdf o pamięci przy ekstrakcji tekstu](https://pypdf.readthedocs.io/en/stable/user/extract-text.html).
