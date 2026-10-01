# A04 — próba produkcyjna, 1.10.2026

## Wynik i granice

Wersja 2.19.6, commit `0eaa3e3983e36afdc6386b9e57dd1c1081692beb`.
Godziny w Europe/Warsaw (CEST, UTC+02:00). Próba obejmowała wyłącznie
zatwierdzone dane syntetyczne. Nie zmieniano danych klientów.

**Usuwanie i ochrona współdzielonych plików: zaliczone. Doręczenie alarmu:
niezaliczone — błędny adres odbiorczy z fallbacku do nadawcy. A04 jako całość
pozostaje otwarte.**

## Pierwsza próba i naprawa konfiguracji

1. Pierwsza próba o 10:59–11:24 ujawniła `brak_uprawnien` przy usuwaniu
   plików przez worker. Rejestr zachował zlecenia i ponawiał wykonanie.
   Ręcznie sprzątnięto wyłącznie testowe obiekty; nie było to zaliczenie próby.
2. W Cloudflare porównano identyfikatory dostępu z ustawieniami workera:
   oba magazyny korzystały z jednego tokenu, mającego tylko odczyt prywatnych
   dokumentów i brak dostępu do brandingu. Bez ujawniania wartości sekretów.
3. Po zatwierdzeniu właściciela zapisano Object Read & Write wyłącznie dla
   `smart-chatbot-documents-private` i `smart-chatbot`. Bez uprawnień do
   backupów i administracji bucketami; wartości kluczy nie zmieniono.
4. Render zgłaszał także OOM przy 512 MB. Część zdarzeń wystąpiła podczas
   dodatkowej diagnostyki Django, ale kolejne również bez niej. Nie można
   przypisać wszystkich restartów wyłącznie diagnostyce.
5. O 11:55:25 po zgodzie właściciela zmieniono start na
   `celery -A chatbot_project worker --beat --loglevel=info --concurrency=1`.
   Wdrożenie `dep-dav2s38u01pc7387up3g` zakończyło się `Deploy succeeded | Live`.
   Log potwierdził jeden proces prefork, uruchomienie Beat i gotowość
   o 11:56:06; następnie wykonanie zadań cyklicznych.

Usługa pozostaje Starter 512 MB / 0.5 CPU. Nie dodano usług ani kosztów stałych.
Instancja nadal musi być pojedyncza ze względu na wbudowany Beat.

## Ponowna próba — rzeczywisty worker i R2

Przebieg `A04-20261001-b91c2e`, trzy firmy A/B/C, dwa nieprzetwarzane
dokumenty, łącznie dziewięć plików poniżej 1 KB. Bez kont użytkowników,
płatności, publikacji kluczy widgetu i zadań AI. Przed startem: brak
niezakończonych zleceń oraz brak firm o nazwach tego przebiegu.

Skrypt sprawdzał przed zmianami zakres manifestu, tożsamość magazynu,
właścicieli plików, nieoczekiwane relacje oraz skróty treści syntetycznej.
Nie wywoływał funkcji usuwania ręcznie. Weryfikacja obejmowała stan zlecenia
w bazie i obecność konkretnego obiektu w R2, nie tylko wpis `succeeded` Celery.

| Faza | Wynik |
|---|---|
| Usunięcie dokumentu A, wymiana logo/awatara A i kaskada firmy C | Sześć starych plików usuniętych za pierwszą próbą; nowe obrazy i plik B pozostały |
| Ten sam obraz jako logo i awatar A | Usunięcie jednego odwołania zachowało obraz; zlecenie `zachowany` |
| Usunięcie ostatniego odwołania A | Obraz usunięty, zlecenie `gotowe` |
| Odwołanie A do obrazu należącego również do B | Usunięcie odwołania A nie skasowało obrazu B; zlecenie `zachowany` |
| Końcowe usunięcie firm A/B | Wszystkie dziewięć obiektów nieobecne, zero firm i dokumentów testowych |

Zmiany rozpoczęły się o 12:35:05, ostatnia kontrola plików zakończyła się
o 12:35:36. Łącznie 11 zleceń: dziewięć `gotowe`, dwa `zachowany`.
Każde miało jedną próbę wykonania. Nie było ręcznego kasowania obiektów
ani ręcznego oznaczania ich jako wykonane w ponownej próbie.

## Alarm — wykryta luka konfiguracji odbiorcy

O 12:39:33 utworzono jeden kontrolowany wpis błędu `test_odbioru_a04`.
Nie wyłączano R2 ani dostępu produkcji. Worker odnotował `alarm_at`
o 12:40:05. Po wznowieniu wyłącznie tego wpisu worker zakończył go jako
`gotowe`, za pierwszą próbą. Końcowa kontrola: zero niezakończonych zleceń
globalnie, zero firm i dokumentów testowych.

**Nie jest to potwierdzenie doręczenia.** Na workerze brakowało
`EMAIL_ALERTOW`; kod 2.19.6 użył `DEFAULT_FROM_EMAIL`, czyli
`powiadomienia@agencjasm-art.pl`. Właściciel wyjaśnił, że był to wyłącznie
adres nadawcy, bez skrzynki odbiorczej. Wskazanie go w konfiguracji oraz
znacznik wysyłki nie dowodziły istnienia skrzynki — odbiór poczty niezaliczony.

Poprawka 2.19.7 wymaga jawnej listy `EMAIL_ALERTOW`, obsługuje wielu
odbiorców i usuwa fallback do nadawcy. Kod PR i docelowa konfiguracja
nie są automatycznie uznane za wdrożone. Po wdrożeniu potrzebne są ustawienia
obu usług oraz nowa, uzgodniona wiadomość na wskazane przez właściciela
skrzynki z potwierdzeniem odbioru na każdej z nich.
[Konfiguracja odbiorców](alarmy-operatora.md).

## Pamięć i dalsze kroki

Wykres Rendera przed próbą utrzymywał około 50% limitu, podczas próby
wzrósł do około 70% i na odczytanym odcinku pozostał na tym poziomie.
Są to odczyty wykresu, nie profilowanie procesu. Próba była mała: nie
dowodzi stabilności przy długim ruchu, dużych uploadach ani crawl.

Pozostaje, w kolejności:

1. Wdrożyć poprawkę listy odbiorców, skonfigurować web i worker, potwierdzić
   doręczenie nowego alarmu na obu rzeczywistych skrzynkach.
2. Odebrać niezależny nadzór braku przebiegów workera/Beat; własny alarm
   procesu nie wykryje jego zatrzymania.
3. W izolacji sprawdzić utratę callbacku, niedostępny broker/magazyn,
   przerwanie workera i odzyskanie. Nie psuć produkcyjnego R2.
4. Wykonać kopię i odtworzenie zgodną wersją, sprawdzić kwarantannę
   niezakończonych zleceń oraz czasy odtworzenia.
5. Kontynuować A01/A02 w Stripe test mode, A03/A05 w panelu/widgecie,
   następnie pozostałe bramki komercyjne z roadmapy.

Lokalny scenariusz produkcyjnej próby przeszedł sześć testów zabezpieczeń.
Nie jest to test końcówek HTTP ani zastępstwo dla końcowej macierzy dostępu.
