# Niezależny nadzór Beat i workera — 2.19.8

## Co mierzymy

Co minutę Beat wysyła `accounts.tasks_monitoring.potwierdz_przebieg` zwykłą
kolejką. Worker zapisuje czas publikacji w jednym wierszu tabeli
`accounts_przebiegmonitora`. Publiczny `/health/` odczytuje ten ślad;
nie zleca zadania, nie wysyła poczty i nie odpytuje wszystkich workerów.

Próba łączy Beat, broker, tę samą kolejkę i wykonanie przez worker. Wykrywa
zatrzymanie któregoś z tych elementów albo opóźnienie kolejki. Nie rozstrzyga,
który element zawiódł, nie sprawdza każdej kolejki, każdej funkcji biznesowej,
SMTP, R2 ani rezultatów retencji. Nie zastępuje dotychczasowej diagnostyki.

Brak zapisu, zapis starszy niż 180 sekund, przyszły czas albo błąd odczytu
oznaczają `zadania=false` oraz `stan=ograniczony`, jeśli baza działa.
Świeży zapis daje `zadania=true`. Baza nadal samodzielnie decyduje o HTTP
200/503 i starym polu `status`; nie zmieniamy reguły restartu web w Render.
Odpowiedź ma `Cache-Control: no-store`, aby nie utrwalać zielonego stanu.

Nagłówek czasu powstaje przy publikacji, dzięki czemu opróżnienie starej
kolejki nie odświeża zdrowia datą wykonania. Wiadomości mają ważność 60 sekund;
zadanie dodatkowo odrzuca brakujący, błędny, przyszły lub zbyt stary nagłówek.
Wywołanie bezpośrednie/eager nie tworzy potwierdzenia. Czas w bazie może tylko
rosnąć; opóźniona próba nie nadpisuje nowszej. Zegary usług muszą być zgodne.

## Monitor zewnętrzny

Istniejący monitor słowa kluczowego na `/health/` ma wymagać dokładnego
`"stan": "ok"`. Sam HTTP 200, `"status": "ok"` ani pojedyncze `ok` nie
wykryją częściowej awarii. Sprawdzenie co 5 minut, alarm po dwóch nieudanych
sprawdzeniach daje w przybliżeniu do 13 minut od ostatniej udanej próby
(3 minuty ważności + do 10 minut na monitor), plus dostarczenie powiadomienia.
Jest to wynik przy takim ustawieniu monitoringu, nie gwarancja czasu reakcji.

Alarm wysyła monitor spoza Rendera. `EMAIL_ALERTOW` i zadania Celery nie są
mechanizmem alarmowania o własnym zatrzymaniu. Konfiguracja i doręczenie
powiadomienia z monitora wymagają osobnego odbioru. Nie dodano nowej usługi,
procesu, sekretu ani kosztu stałego; jedynie lekka próba co minutę i wiersz DB.

## Wdrożenie i odbiór krok po kroku

1. Scalić PR, zastosować migrację `accounts.0045_przebieg_monitora`, wdrożyć
   obie role: web oraz worker z Beat. Worker zachowuje concurrency=1.
2. Przed pierwszą próbą stan ograniczony jest prawidłowy. Sprawdzić w logu
   workera rejestrację i wykonanie nowego zadania, następnie `/health/`:
   wersja 2.19.8, baza=true, broker=true, zadania=true, stan=ok.
3. Zweryfikować w istniejącym monitorze dokładne słowo kluczowe, częstotliwość,
   próg i rzeczywistych odbiorców. Nie utożsamiać listy EMAIL_ALERTOW z listą
   powiadomień zewnętrznego monitora.
4. W izolowanym środowisku zatrzymać samo Beat, pozostawiając broker i web.
   Po ponad 180 s od ostatniej publikacji ma być HTTP 200, broker=true,
   zadania=false, stan=ograniczony. Wznowić Beat i sprawdzić powrót do ok.
5. Powtórzyć próbę przy zatrzymanym workerze i działającym Beat. Po wznowieniu
   zaległe wiadomości nie mogą odnowić zdrowia; potrzebna świeża próba.
6. Potwierdzić powiadomienie zewnętrznego monitora na kontrolowanym celu
   testowym oraz zapisać czas wykrycia, doręczenia i powrotu do zdrowia.
   Nie zatrzymywać produkcyjnych usług w ramach tej próby.
7. Zapisać commit, wdrożenia i wyniki. Zielone CI nie oznacza wykonania
   powyższego odbioru infrastruktury produkcyjnej.

Przy rollbacku pozostawić tabelę (jest addytywna); stary kod ją ignoruje,
ale traci się wykrywanie ciszy workera. Po odtworzeniu kopii stary znacznik
przestaje być ważny po 180 s, a nowy powstaje dopiero po wznowieniu kolejki.
Środowisko odtwarzania musi pozostać odizolowane od produkcyjnego brokera.

## Dowody przed wdrożeniem

Testy obejmują brak i starzenie śladu, odzyskanie, wiek od publikacji,
niepoprawne czasy, zapis poza kolejnością, eager, błąd odczytu i zgodność
rejestracji harmonogramu. Próba integracyjna uruchamia Scheduler, transport
Kombu w pamięci i worker solo z prawdziwym zapisem do testowego PostgreSQL.
Nie jest to test konfiguracji Redis/Render/UptimeRobot ani doręczenia alarmu.
