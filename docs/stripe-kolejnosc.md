# A02 — kolejność synchronizacji abonamentu

30.09.2026, wersja 2.19.2. Kod przygotowany do odbioru; nie jest to potwierdzenie
wdrożenia ani zamknięcie A03–A05. Wymaga zmian A01 z PR #109.

## Błąd i poprawka

Żądanie A pobierało `active`, po czym zatrzymywało się przed zapisem. Żądanie B
pobierało `canceled` i zawieszało abonament. A wracało i przywracało dostęp na
podstawie starej odpowiedzi. Ten sam problem cofał zmianę planu i `past_due`.
Przed poprawką trzy testy tego przeplotu wykazały błędny stan końcowy.

Wspólna funkcja synchronizacji przyjmuje wyłącznie ID abonamentu. Najpierw
uzyskuje transakcyjną blokadę PostgreSQL dla firmy, potem pobiera aktualny stan
Stripe, sprawdza powiązanie z firmą i zapisuje Subscription oraz odbicie Tenant.
Blokada trwa do zatwierdzenia transakcji, a rollback lub zerwanie połączenia ją
zwalnia. Jej klucz jest stabilny między procesami i obejmuje całą firmę, również
gdy zmienia się ID abonamentu. Wyjątkowo kolizja skrótu może jedynie odroczyć
niezależną firmę; nie pozwala pominąć blokady.

Webhook wykonuje pierwszy odczyt tylko do rozpoznania firmy; jego wynik nie
jest zapisywany. Dopiero odczyt pod blokadą jest źródłem zmian. Panel i zadanie
używają tej samej funkcji. Nie porównujemy `event.created`, ponieważ powrót
z Checkout oraz zadanie okresowe nie są zdarzeniami Stripe.

Gdy firma jest już synchronizowana, webhook oddaje 500 do ponowienia przez
Stripe, a panel 503 z dotychczasowym komunikatem o ponownej próbie. Zadanie
odkłada firmę do kolejnego przebiegu. Nie czekamy na blokadę w zajętym procesie.
Podczas odczytu sieciowego nie blokujemy Tenant używanego przez czat i limity.
Zapis nadal blokuje Tenant na krótko. HTTP Stripe ma limit 10 s z A01.

Nie gwarantuje to, że Stripe nie zmieni się już po odczycie. Następne zdarzenie
lub kontrola okresowa uzgodnią taką zmianę. Konflikt dwóch aktywnych abonamentów
nie przełącza dostępu między nimi: wymaga wyjaśnienia przez operatora.

## Kontrola okresowa i zakres

- Istniejący Celery Beat zleca `accounts.tasks_stripe.uzgodnij_platnosci` co 5 min.
  Zadanie jest importowane przez `accounts.tasks`, więc worker je rejestruje.
- Jeden przebieg wybiera maksymalnie 25 firm, najpierw nigdy niesprawdzone,
  następnie najdawniej sprawdzone. Firma jest kwalifikowana najwcześniej po godzinie
  od ostatniej próby. Błąd także zapisuje próbę, żeby nie zagłodzić innych firm.
- Po 50 s nie rozpoczyna się kolejnej firmy. Trwająca operacja kończy się w ramach
  timeoutów Stripe. Limity Celery: miękki 110 s, twardy 120 s; wiadomość wygasa
  po 300 s. Przy awarii procesu po zapisaniu próby firma wraca najpóźniej po
  godzinie do puli kwalifikujących się, a niekoniecznie zostaje wtedy obsłużona.
- Zakres to zapisane `Subscription.stripe_subscription_id` oraz znane sesje
  `ProbaZakupu.sesja_id`. Zakończona sesja może odtworzyć zakup bez żadnego webhooka.
  Nie tworzymy sesji, nie obciążamy kart, nie anulujemy abonamentów i nie robimy zwrotów.
- `KontrolaStripe` przechowuje ostatnią próbę, ostatnie udane uzgodnienie, kod
  problemu oraz czas alarmu. Nie przechowuje sekretów ani danych karty.
- Nieudane uzgodnienie wysyła zbiorczy alarm na istniejący `EMAIL_ALERTOW`
  (z dotychczasowym fallbackiem do `DEFAULT_FROM_EMAIL`). Ten sam problem wraca
  w alarmie nie częściej niż co godzinę; brak dostarczenia nie ustawia znacznika.
  Jednoczesne kopie zadania mogą wysłać powtórzony alarm — nie obiecujemy exactly-once.
- Raport jest włączony do istniejących kopii danych i usuwany wraz z firmą.

**Ograniczenia:** nie jest to skan wszystkich historycznych abonamentów konta
Stripe. Nie odnajdzie zakupu, dla którego nie znamy ani ID abonamentu, ani ID
sesji. Nieznana odpowiedź create z A01 nadal wymaga `uzgodnij_checkout`.
Limit pracy oznacza, że duża kolejka lub awaria Stripe może wydłużyć czas
uzgodnienia. Raport sprawdza także brak udanego uzgodnienia przez dobę.
Zatrzymany worker/Beat nie wyśle własnego alarmu: ich działanie i dostarczanie
alarmów trzeba objąć istniejącym nadzorem operacyjnym.

## Raport i reakcja operatora

Domyślnie komenda czyta wyłącznie lokalną bazę, bez Stripe i bez zmian:

```text
python manage.py kontrola_stripe
python manage.py kontrola_stripe --check
python manage.py kontrola_stripe --tenant 123
```

`--check` zwraca błąd, gdy istnieje problem, brak jakiegokolwiek sukcesu lub
ostatni sukces jest starszy niż doba. Raport liczy wszystkie zaległości,
wypisuje maksymalnie 100 identyfikatorów firm, bez adresów e-mail i sekretów.
Na początku po migracji brak sukcesu jest spodziewany do pierwszej kontroli.

1. Sprawdzić działanie workera/Beat oraz log `Kontrola Stripe`.
2. Sprawdzić odpowiednią firmę i abonament w tym samym koncie i trybie Stripe.
3. Przy konflikcie dwóch abonamentów podjąć decyzję o prawidłowym wiązaniu;
   nie kasować danych ani nie wykonywać zwrotów wyłącznie na podstawie alarmu.
4. Po usunięciu przyczyny można wykonać
   `python manage.py kontrola_stripe --tenant 123 --uzgodnij`.
   Ta opcja aktualizuje lokalny dostęp według Stripe; respektuje godzinny odstęp
   od poprzedniej próby. Zwykłe webhooki nie mają tego odstępu.
5. Sprawdzić świeży sukces w raporcie oraz rzeczywiste dostarczenie alarmu
   testowego w środowisku testowym. Sukces SMTP sam w sobie nie dowodzi odbioru.

## Wdrożenie i odbiór krok po kroku

1. Odebrać CI oraz testy integracyjne Stripe w test mode: anulowanie, odnowienie,
   zmiana planu, `past_due`, dwa równoległe webhooki i powrót z Checkout.
2. Zastosować migrację `accounts.0042_kontrola_stripe` przed uruchomieniem zadania.
   Nie wymaga nowego sekretu, płatnej usługi ani zmiany kontraktu frontendu.
3. Wdrożyć zgodną wersję web/workera/Beat. Stary web nadal potrafi zapisać dawną
   migawkę; poczekać na zakończenie jego żądań i wyłączenie starych procesów.
   Jeżeli wymagamy ochrony przez cały czas przełączenia, krótko wstrzymać webhook
   (odpowiedź 503, żeby Stripe ponowił) i potwierdzenie zakupu do końca przełączenia.
4. Potwierdzić `/health/` 2.19.2, zarejestrowanie zadania i jego pierwszy przebieg.
5. Uruchomić lokalny raport kontroli i odebrać pierwsze uzgodnienia. Sprawdzić,
   czy limit partii wystarcza dla liczby firm; alarmy wymagają działającej poczty.
6. W test mode pominąć webhook, potwierdzić naprawę przez zadanie oraz zasymulować
   awarię Stripe i odbiór alarmu. Nie wykonywać realnych obciążeń do tego testu.
7. Dopiero po tych kontrolach oznaczyć A02 jako wdrożone i odebrane.

Rollback: zatrzymać nowe zadanie/Beat przed cofnięciem kodu; tabelę można zachować.
Stara wersja przywraca ryzyko A02. Po rollbacku uzgodnić stan przed ponownym
odbiorem płatności. Nie cofać A01 i jego tabeli prób zakupu.

Źródła: [blokady transakcyjne PostgreSQL](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS),
[kolejność i ponowienia webhooków Stripe](https://docs.stripe.com/webhooks).
