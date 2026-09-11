# Potwierdzenie e-maila — F07, część 2

## Przepływ i kontrakt API

1. POST `/api/accounts/register/` waliduje dane firmy i zwraca 202
   z `verification_required: true`. Hasło jest opcjonalne dla zgodności ze starym
   klientem; jeśli podane, przechodzi walidację, ale nie zostaje zapisane.
2. Zgłoszenie PendingRegistration zawiera dane firmy oraz skrót SHA-256 losowego
   tokena (32 bajty entropii). Nie powstają użytkownik, firma, klucz widgetu,
   subskrypcja ani sesja Stripe.
3. E-mail prowadzi do `FRONTEND_URL/potwierdz-email#token=...`. Panel usuwa
   fragment z adresu i trzyma token tylko w pamięci karty. Link wygasa po
   24 godzinach; siedem dni od zgłoszenia wyznacza maksymalny czas jego życia.
4. POST `/api/accounts/registration/preview/` z tokenem zwraca adres i nazwę
   firmy. Nie aktywuje konta. GET nie zużywa tokena, także przy skanowaniu poczty.
5. POST `/api/accounts/registration/activate/` z tokenem i nowym hasłem blokuje
   zgłoszenie, ponownie sprawdza ważność i e-mail, tworzy użytkownika, firmę,
   dane rozliczeniowe i trial w jednej transakcji. Zwraca 201, `use_trial`
   i wybrany `plan`, bez JWT. Panel kieruje do logowania. Przy płatnym wariancie
   właściciel po zalogowaniu przechodzi do wyboru planu i Checkout w panelu.
6. Zużyty token nie działa ponownie. Dane firmy i skrót są od razu usuwane ze
   zgłoszenia. Awaria transakcji pozostawia link gotowy do ponowienia.

Hasło ustala osoba mająca dostęp do wiadomości. Wcześniejsze hasło podane
przez kogoś, kto jedynie zna cudzy adres, nigdy nie staje się hasłem konta.
Istniejące konta zachowują dostęp; migracja nie oznacza ich jako zweryfikowanych
i nie wymusza ponownej aktywacji.

## Ponawianie i błędy

POST `/api/accounts/registration/resend/` przyjmuje wyłącznie e-mail.
Zwraca ten sam komunikat 202 dla adresu nieznanego, aktywnego i oczekującego.
Nie deklarujemy identycznego czasu odpowiedzi: SMTP jest synchroniczne.
Limit bazy: jedna wiadomość/minutę, maksymalnie pięć na adres w oknie 24 godzin.
Nowy link unieważnia poprzedni. Ponowienie rejestracji może poprawić dane firmy
dopiero przy wystawieniu nowego tokena; wcześniej odczytany link nie zaakceptuje
podmienionego profilu.

Limity cache: ponowienie 10/IP/h i 30 globalnie/min, aktywacja 20/IP/h i
60 globalnie/min, podgląd 60/IP/min i 300 globalnie/min. Awaria wspólnego cache
wstrzymuje operację (503), przekroczenie limitu daje 429 z Retry-After.
Limit wiadomości na adres jest w PostgreSQL i przeżywa reset Redisa.

Awaria SMTP daje 503 bez ujawniania szczegółów połączenia i nie tworzy konta.
Zgłoszenie pozostaje; klient może ponowić wysyłkę po minucie. To nie jest outbox
z automatycznym retry: po przerwaniu procesu użytkownik korzysta z ponowienia.
Otwarcie strony ponownie lub jej odświeżenie wymaga powrotu do linku z e-maila,
ponieważ celowo nie zapisujemy tokena w localStorage/sessionStorage.

## Wdrożenie na obecnych zasobach

1. Skoordynuj wdrożenie panelu i backendu: stary panel po odpowiedzi 202 próbował
   od razu logować i nie ma ekranu aktywacji. Nowy panel bez nowego API nie może
   rozpocząć rejestracji. Zaplanuj krótkie okno dla nowych rejestracji; istniejące
   logowanie i konta działają niezależnie od tej zmiany.
2. Wykonaj standardową kopię przed migracją i `python manage.py migrate`
   (accounts.0034_pending_registration). Wdróż backend 2.0.6 i zgodny panel.
3. Sprawdź `FRONTEND_URL`: docelowy adres panelu z HTTPS, bez fragmentu,
   query string i poświadczeń. Używane są obecne SMTP/DEFAULT_FROM_EMAIL,
   EMAIL_TIMEOUT oraz REDIS_URL. Nowy sekret ani płatna usługa nie są wymagane.
4. Na syntetycznym adresie operatora sprawdź pełny przepływ z rzeczywistą pocztą:
   rejestracja → link → hasło → logowanie → trial; potem ponowienie, wygaśnięcie,
   duplikat kliknięcia, błędne hasło, awaria/limit i płatny wariant.
5. Uruchamiaj `python manage.py purge_pending_registrations` codziennie na
   istniejących zasobach; `--dry-run` pokazuje liczbę bez kasowania. Usuwa wyłącznie
   zgłoszenia starsze niż siedem dni. Podłącz alarm braku przebiegów w ramach F21.
   Samo dodanie polecenia nie oznacza uruchomienia harmonogramu na produkcji.

Przygotowanie PR nie zmienia produkcji i nie wysyła wiadomości do klientów.
Wyniki testów oraz kolejność powiązanych PR-ów znajdują się w ich opisach.

## Pozostały odbiór

Weryfikacja e-maila ogranicza tworzenie triali z dowolnym cudzym adresem;
nie zapobiega osobnym skrzynkom ani aliasom. Nie deklarujemy pełnego systemu
antyfraudowego. Nadal wymagane: rzeczywisty adres klienta za proxy, monitorowanie
odrzuceń i dostawy SMTP, alarm retencji, odbiór produkcyjny oraz testy zgodności
rozliczeń. MFA, reset hasła i sesje pozostają F14/F15/F22; idempotencja Stripe F11.
