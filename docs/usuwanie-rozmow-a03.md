# A03/A05 — usuwanie rozmów i wykonalna retencja (2.19.3)

Stan: przygotowana poprawka i testy, **bez wdrożenia oraz odbioru produkcji**.
Wymagane są powiązane zmiany backendu i frontend_chatbot. Wyniki pełnego CI
i numery PR są w opisach PR. Poprawka nie wymaga nowej płatnej usługi.

## 1. Odtworzony problem

Zapis odpowiedzi składał się z osobnych zapisów wiadomości, użycia i promptu.
Usunięcie rozmowy pomiędzy nimi mogło pozostawić treść bez rozmowy, ponieważ
trzy relacje używały SET_NULL. Awaria zapisu promptu pozostawiała wcześniejsze
części odpowiedzi. Ponowione żądanie z dawnym UUID mogło odtworzyć sesję.
API retencji przyjmowało m.in. wartości logiczne, obcinało ułamki i dopuszczało
liczby, dla których wyliczenie daty usuwania kończyło się przepełnieniem.

## 2. Co zmienia kod

1. Zapis odpowiedzi, użycia i promptu jest jedną transakcją. Zapis blokuje
   wiersz rozmowy i sprawdza firmę. Błąd dowolnej części cofa całą odpowiedź.
2. Zapis wiadomości, promptu, użycia i kontaktu do istniejącej rozmowy bierze
   tę samą blokadę. Spóźniony zapis do usuniętej rozmowy kończy się HTTP 410.
3. Usuwanie przez endpoint prywatności, retencję i czyszczenie testu bota
   blokuje sesję, następnie wiersz rozmowy. CASCADE usuwa powiązane wiadomości,
   oceny, logi oraz kontakty. Transakcja obejmuje również znacznik usunięcia.
4. Znacznik zawiera firmę i SHA-256 identyfikatora sesji z identyfikatorem firmy;
   nie zawiera treści, IP ani surowego UUID. Pozostaje do usunięcia firmy,
   aby późne ponowienie nie odtworzyło skasowanej sesji. To nadal identyfikator
   służący do rozpoznania powtórki, nie deklaracja pełnej anonimizacji.
5. Publiczny czat i kontakt odmawiają użycia usuniętej sesji. Kontakt wysłany
   przed pierwszym pytaniem dostaje rozmowę, jeżeli żądanie zawiera UUID.
   Kontakt bez UUID pozostaje samodzielnym rekordem z własną retencją.
6. SSE kończy usuniętą rozmowę zdarzeniem
   `{"type":"error","code":"conversation_deleted","message":"..."}`,
   bez późniejszego `done`. Sprawdzenie odbywa się przy odczycie zdarzeń
   dostawcy, najwyżej raz na 0,25 s; nie jest to niezależny zegar przerywający
   blokujące połączenie sieciowe. Dostawca jest zamykany również po rozłączeniu.
7. Widget obsługuje HTTP 410 i terminalny błąd SSE: usuwa lokalną historię,
   dawny UUID i stan formularza, pokazuje wyjaśnienie. Dopiero nowe pytanie
   tworzy nowy UUID. Nie wysyła ponownie starego pytania automatycznie.
   Panel testowy usuwa częściową odpowiedź, a czyszczenie przerywa odbiór.
8. Formularz kontaktowy nie pokazuje sukcesu po odrzuceniu żądania.
9. Retencja pomija zajętą rozmowę i sprawdza także świeże logi oraz kontakty.
   Import do istniejącej rozmowy blokuje jej wiersz przed zapisem zbiorczym.
10. API akceptuje całkowite dni 0–3650 oraz tekstową liczbę całkowitą.
    Odrzuca bool, float (także 30.0), null i wartości poza zakresem. Ograniczenie
    jest także w modelu i bazie. 0 nadal wyłącza retencję, domyślne 90 zostaje.
    Granica 3650 to limit techniczny, nie zalecana polityka przechowywania.
11. Komenda `kontrola_retencji` raportuje nieprawidłowe okresy bez zmian danych.
    Migracja odmawia wykonania przy takich wartościach. Zadanie retencji i jego
    diagnostyka mają dodatkową ochronę przed przepełnieniem wyliczenia daty.

## 3. Kontrakt i granice gwarancji

Blokady bazy trwają tylko podczas krótkich zapisów/usuwania, nie podczas AI
ani SMTP. Kolejność to blokada sesji, potem wiersz rozmowy; zapis istniejącego
rekordu bierze tylko wiersz. Nie dodawać ścieżki, która odwraca tę kolejność.
Nowe `bulk_create`, `QuerySet.update`, surowy SQL i zadania importujące muszą
osobno przestrzegać protokołu — metoda `save` nie przechwytuje takich operacji.
CASCADE działa także przy usuwaniu ORM poza helperem, ale znacznik powstaje
tylko przez `usun_rozmowe`; wszystkie ścieżki usuwania sesji powinny go używać.

Nie można wycofać bajtów już wysłanych do przeglądarki lub dostawcy AI,
wyeksportowanego CSV, e-maila ani rozpoczętej wysyłki SMTP. Stara otwarta
przeglądarka pozna usunięcie przy kolejnym żądaniu/zdarzeniu, nie przez push.
Usunięcie po naliczonej pracy AI nie zwraca wykorzystanej wiadomości z limitu.

Migracja nie kasuje dawnych logów z `conversation_id=NULL`: nie ma wiarygodnej
relacji pozwalającej przypisać je do konkretnej skasowanej rozmowy. Nadal
obejmuje je retencja po wieku. Nie usuwamy ich masowo bez odrębnej decyzji.
Znaczniki nie są rekonstruowane dla rozmów usuniętych przed wdrożeniem.

Kopia zapasowa sprzed usunięcia może zawierać treść i nie mieć znacznika.
Odtworzenie wymaga ponownego zastosowania późniejszych żądań usunięcia przed
otwarciem dostępu. Ta poprawka nie wprowadza niezależnego od kopii rejestru
żądań usunięcia. Zasady retencji kopii i procedura odtworzenia pozostają
osobnym elementem odbioru operacyjnego.

## 4. Kolejność wdrożenia przez operatora

1. Potwierdzić zielone CI obu PR-ów i sprawdzoną kopię bazy.
2. Wdrożyć frontend obsługujący 410/error. Jest zgodny także ze starym backendem.
3. Sprawdzić obecne okresy retencji przed migracją. Przy dostępnym nowym kodzie:
   `python manage.py kontrola_retencji`. Komenda tylko czyta istniejącą tabelę.
   Jeśli proces Rendera migruje bazę zanim da dostęp do nowego kodu, wykonać
   poniższy odczyt w dotychczasowej powłoce Django:

   ```python
   from accounts.models import Tenant

   list(
       Tenant.objects.filter(data_retention_days__gt=3650).values_list("id", "data_retention_days")[
           :100
       ]
   )
   ```

4. Wynik musi być pusty. Jeśli nie jest, ustalić okres z administratorem danej
   firmy i poprawić ustawienie; nie normalizować wartości automatycznie do
   krótszego czasu ani nie uruchamiać czyszczenia na próbę.
5. Zaplanować krótkie wstrzymanie nowych żądań czatu, kontaktu i usuwania oraz
   zadania retencji. Dokończyć stare żądania i zatrzymać stare procesy. Mieszana
   wersja kodu nie daje gwarancji: stary proces nie bierze nowych blokad.
6. Zastosować migracje `accounts.0043_usuwanie_retencja` i
   `chat.0008_usuwanie_retencja`, uruchomić nowy web i worker. Schemat i kod
   muszą przejść razem; samo scalenie PR nie kończy etapu.
7. Sprawdzić `/health/` (2.19.3), kontrolę retencji oraz logi startowe web/workera.
8. Wykonać poniższy odbiór na wydzielonej firmie z syntetycznymi danymi.
9. Przywrócić ruch i harmonogram po odbiorze; zapisać commit, czas oraz wyniki.
   Obserwować błędy 500, blokady bazy i pierwszy zaplanowany przebieg retencji.

## 5. Odbiór

- Zwykły czat, SSE, kontakt przed i po pierwszym pytaniu oraz test bota działają.
- Usunięcie w trakcie odpowiedzi nie pozostawia rozmowy, promptu, logu użycia
  ani kontaktu. Widget czyści treść; kolejne świadomie wysłane pytanie działa.
- Powtórka starego UUID daje 410; UUID rozmowy innej firmy nie daje dostępu.
- Czyszczenie testu bota usuwa również jego logi i nie przywraca fragmentu SSE.
- PATCH retencji z bool/ułamkiem/3651/dużą liczbą zwraca 400 i zachowuje ustawienie.
  Granice 0 i 3650 oraz dotychczasowe standardowe okresy działają.
- `purge_expired_data --dry-run` to tylko podgląd; różnice z późniejszym
  przebiegiem są możliwe przy równoległych zapisach i blokadach. Nie uruchamiać
  rzeczywistego czyszczenia produkcji jako testu wdrożenia.

## 6. Weryfikacja automatyczna i wycofanie

Lokalna regresja backendu: 121 testów, w tym prawdziwy równoległy zapis/usunięcie
na PostgreSQL, rollback częściowego zapisu i usunięcia, odmowa migracji na
złych danych, izolacja firm, spóźnione zapisy, SSE oraz zachowanie naliczenia.
Testy interfejsu sprawdzają HTTP 410, błąd SSE z późniejszą deltą w tym samym
pakiecie, nowy UUID i brak fałszywego sukcesu formularza. Dokładny końcowy
wynik wszystkich testów i bramek pozostaje przy PR-ach.

Wycofanie kodu przywraca podatność na wyścig. Zatrzymać ruch i retencję,
sprawdzić błąd, preferować poprawkę do przodu. Nie cofać migracji chat.0008
automatycznie: jej odwrócenie usuwa tabelę znaczników i możliwość blokowania
starych UUID. Usuniętej treści nie przywraca się samym cofnięciem migracji.
Odtworzenie kopii to osobna kontrolowana procedura, nie rutynowy rollback.

## 7. Dalej

A04: trwałe zlecenia usuwania plików, ponowienia po awarii magazynu i alarmy.
Nadal do odbioru: wdrożenia A01/A02, infrastruktura, kopie/restore z obsługą
usunięć, scenariusze dostępu, obciążenie i rzeczywiste przepływy użytkownika.
