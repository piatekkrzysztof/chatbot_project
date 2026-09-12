# Powiadomienia o zmianie hasła — 2.0.13

Zakres: zmiana własnego hasła przez ustawienia oraz potwierdzenie resetu.
Nie obejmuje administracyjnych zmian hasła przez Django admin, konsolę lub
bezpośredni zapis do bazy. Nie dodaje nowego sposobu resetowania hasła/MFA.

## Zapis i dostawa

`PasswordNotification` powstaje w tej samej transakcji co hasło. Awaria zapisu
kolejki wycofuje hasło, odwołanie sesji i zużycie kodu MFA. Wycofanie dalszej
części transakcji usuwa też powiadomienie. Ani SMTP, ani broker nie są wywoływane
z tego żądania. Nie ma powiadomień historycznych ani wysyłki po samym wdrożeniu.

Wiersz zawiera UUID, użytkownika, adres odbiorcy z chwili zmiany, czas zdarzenia,
stan, liczbę prób i stały kod błędu. Nie zapisujemy hasła, jego skrótu, tokena
resetu ani kodu MFA. Zmiana adresu przed wysyłką nie przekierowuje powiadomienia.
Nie udostępniamy tabeli przez API ani panel administracyjny. Usunięcie konta
usuwa jego rekordy kolejki; wiadomości już przekazanej SMTP nie można wycofać.

Obecny Celery beat raz na minutę uruchamia `accounts.tasks.send_password_notifications`.
Jedno zadanie podejmuje najwyżej 10 rekordów. Wysyłkę poprzedza krótka
transakcja z `select_for_update(skip_locked=True)` i zapis pięciominutowej
rezerwacji. SMTP działa poza transakcją i poza blokadą użytkownika. Dwa workery
nie przejmą tej samej aktywnej rezerwacji. Wynik może zapisać tylko jej posiadacz.

- Stany: `pending` → `sending` → `sent`, albo ponowienie `pending` / końcowe `failed`.
- Maksymalnie pięć prób łącznie, również po przerwaniu procesu. Odstępy po
  błędach: 60, 120, 240 i 480 sekund, z dokładnością do cyklu workera.
- Zawieszona próba jest ponownie dostępna po pięciu minutach; wyczerpanie
  limitu po przerwaniu ostatniej próby daje `failed`, bez szóstej wysyłki.
- Timeout połączenia SMTP: 15 sekund; zadanie ma soft limit 210 s i hard limit
  240 s, krótszy niż rezerwacja. Produkcyjny worker powinien używać puli prefork
  obsługującej limity Celery. Nie uruchamiać tego zadania inline na web.
- Zlecenia beat wygasają po 60 s, aby nie kumulować starych skanów w brokerze.
  Zdarzenia w bazie nie znikają po utracie zlecenia lub awarii brokera.
- `sent` oznacza przyjęcie wiadomości przez backend pocztowy/SMTP, a nie dowód
  pojawienia się w skrzynce. Odbiór należy sprawdzić osobno.

SMTP i baza nie mają wspólnej transakcji. Jeśli serwer przyjmie wiadomość,
a worker straci odpowiedź albo zapis wyniku, retry może dostarczyć drugi egzemplarz.
Stały `Message-ID` pomaga korelować próby; nie gwarantuje deduplikacji u odbiorcy.
Nie obiecujemy dostawy dokładnie raz.

## Kontrola i obsługa błędów

`python manage.py check_password_notifications` jest odczytowe. Wypisuje tylko
liczniki stanów i liczbę oczekujących/rezerwowanych zdarzeń starszych niż 10 minut.
Kończy się błędem, gdy są zaległe lub `failed`. Nie wysyła poczty, nie ponawia
zakończonych zadań i nie drukuje odbiorców. Log wysyłki zawiera UUID i numer próby,
bez treści odpowiedzi SMTP. Próg 10 minut sygnalizuje opóźnienie również wtedy,
gdy automat jeszcze ponawia; nie oznacza wyczerpania wszystkich prób.

Po błędzie operator sprawdza proces worker/beat, połączenie z bazą i brokerem,
konfigurację SMTP oraz wynik powyższego polecenia. `failed` zachowujemy do
świadomej obsługi: bez automatycznego zerowania liczby prób i bez ponawiania
wszystkich historycznych zdarzeń. Ewentualne ręczne ponowienie wymaga rozpoznania
konkretnego zdarzenia i możliwej wcześniejszej dostawy.

Wpięcie kontroli do niezależnego alarmu oraz retencja rekordów pozostają następnym
etapem. Logowanie błędu i obecność harmonogramu w kodzie nie potwierdzają alarmowania
na produkcji. Ten PR nie włącza automatycznego usuwania danych.

## Wdrożenie

1. Wymagane są dotychczasowe DATABASE_URL, Redis, DJANGO_SECRET_KEY, FRONTEND_URL
   i konfiguracja SMTP na workerze. FRONTEND_URL musi wskazywać zaufany panel;
   w produkcji wymagamy HTTPS bez danych logowania, query i fragmentu.
2. Zastosować `accounts.0037_password_notification` przez build web. Migracja
   dodaje pustą tabelę i indeks; nie zmienia istniejących haseł/MFA/sesji.
3. Wdrożyć web i worker z tego samego commita. Jeśli automatyczny deploy workera
   wyprzedzi migrację, jego nowe zadanie może zgłosić brak tabeli. Następny cykl
   podejmie pracę po migracji; stare funkcje logowania nie potrzebują tej tabeli.
4. Potwierdzić web 2.0.13 oraz nowy worker, działający beat i rozpoznanie zadania.
   Nie potrzeba dodatkowej usługi ani zmian panelu #15.
5. Uruchomić odczytową kontrolę kolejki. Na uzgodnionym koncie testowym zmienić
   hasło w panelu, potwierdzić odbiór e-maila i odwołanie poprzednich sesji.
   Osobno powtórzyć reset: wiadomość z linkiem, zmiana hasła, powiadomienie.
6. Sprawdzić nadawcę, czas i treść, brak sekretów oraz zachowane MFA. Zapisać
   wynik dostawy i wdrożenia w roadmapie. Automatyczne testy używają atrap poczty;
   nie są dowodem produkcyjnej dostawy.

Rollback: cofnąć web i worker do 2.0.12, zachowując nową tabelę i dane.
Nie cofać migracji na produkcji ani nie odtwarzać starych haseł z backupu.
Już zakończone sesje pozostają zakończone. Oczekujące wiadomości poczekają na
ponowne uruchomienie zgodnego workera; świadomie uwzględnić wiek kolejki przed
wznowieniem. Po rollbacku nowe zmiany hasła nie tworzą powiadomień.

## Walidacja

Regresje obejmują obie ścieżki zmiany, brak zlecenia po błędnej walidacji/MFA,
rollback hasła i kodu, niewidoczność niezatwierdzonej transakcji dla workera,
duplikaty, dwa równoległe workery i zmiany hasła, retry, zero wysłanych wiadomości,
utracony zapis po SMTP, przerwanie procesu, limit prób, oryginalnego odbiorcę,
prywatność logów, nieprawidłowy URL panelu i odczytową kontrolę kolejki.
Końcowe wyniki CI i liczby testów znajdują się w opisie PR-a.
