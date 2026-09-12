# Odzyskiwanie hasła i potwierdzenie konfiguracji MFA

Etap F14/F15/F22, wersja 2.0.11. Kod przygotowany do wdrożenia; rzeczywiste
doręczenie poczty resetującej pozostaje do odbioru po uruchomieniu obu usług.

## Zachowanie

- Panel udostępnia `/odzyskaj-haslo` i `/reset-hasla` oraz link przy logowaniu.
- `POST /api/accounts/password-reset/request/` przyjmuje `email`, zwraca 202
  z tą samą treścią dla istniejącego i nieistniejącego konta. Wyszukiwanie
  konta i SMTP odbywają się wyłącznie w zadaniu workera. 202 oznacza przyjęcie
  prośby, nie potwierdzenie doręczenia. Konto nieaktywne lub bez hasła nie
  otrzyma wiadomości; reset nie aktywuje konta.
- Django PasswordResetTokenGenerator wiąże link z kontem, hasłem, e-mailem
  i last_login. Link wygasa po 1800 sekundach. Kilka zamówionych linków może
  być jednocześnie ważnych, ale pierwsza skuteczna zmiana hasła unieważnia
  wszystkie. Ponowne zamówienie samo nie unieważnia wcześniejszego linku.
- Token trafia do fragmentu URL `#uid=…&token=…`. Panel usuwa fragment
  z bieżącego wpisu historii i trzyma go w pamięci; nie zapisuje go w storage.
  Fragment nie jest wysyłany w HTTP. Strony i API mają no-store/no-referrer.
  Nie należy kopiować pełnych linków do zgłoszeń, analityki ani logów.
- `preview/` sprawdza `uid` i `token`, bez zużycia i ujawniania adresu konta.
  `confirm/` dodatkowo przyjmuje `password`. Hasło sprawdzają walidatory
  Django. Blokada wiersza konta serializuje reset z drugim resetem,
  logowaniem i odświeżaniem. Po zapisie wszystkie LoginSession są odwołane.
  Samo otwarcie linku lub błąd walidacji nie zmienia hasła.
- Reset nie wydaje JWT, nie loguje automatycznie, nie wyłącza MFA i nie
  odnawia kodów zapasowych. Utrata telefonu i wszystkich kodów zapasowych
  wymaga osobnej, jeszcze nieopracowanej procedury odzyskania MFA.
- Rozpoczęcie MFA wymaga `haslo`; potwierdzenie wymaga `haslo` i `kod`.
  Panel używa tego samego podanego hasła w obu krokach, trzyma je wyłącznie
  w pamięci formularza i czyści po zakończeniu lub anulowaniu.

## Limity i awarie

Wymagany istniejący wspólny cache. Brak cache/brokera lub próba pracy
synchronicznej w produkcji daje 503. Nie ma awaryjnej wysyłki SMTP w HTTP.

| Operacja | Limit |
|---|---|
| Prośba o link | 10/IP/godz., 30 globalnie/min |
| Preview i potwierdzenie łącznie | 30/IP/5 min, 120 globalnie/min |
| E-mail (także nieznany) | 1/min, maks. 5/24 godz. |

Liczniki IP/globalne używają stałych okien. Licznik e-mail wygasa 24 godziny
od pierwszej próby. Przekroczenie limitu e-mail pozostawia ogólną odpowiedź
202; pozostałe limity dają 429. Klucze liczników są HMAC, bez jawnego adresu.
Nadużycia z wielu IP/aliasów i wiarygodność IP za proxy pozostają do odbioru.

Zadanie ma termin rozpoczęcia 5 minut i maksymalnie 2 ponowienia po 60 s
po błędzie SMTP. Stary backlog nie wysyła linków po terminie zadania.
Samo ponowienie nie gwarantuje dokładnie jednej wiadomości. Nie ma trwałego
outboxa z potwierdzeniem doręczenia; alarmy kolejki/SMTP pozostają zadaniem
operacyjnym. Nie wysyłamy jeszcze osobnego powiadomienia po zmianie hasła.

Sentry wyłącza domyślne PII, body i zmienne lokalne; hook usuwa body/cookies
oraz args/kwargs z celery-job. Nie oznacza to zamknięcia całego F20 — nadal
potrzebny przegląd innych źródeł logów, dziennika, retencji i uprawnień.

## Kolejność wdrożenia i odbiór

1. Wdrożyć nowy panel. Dodatkowe pole `haslo` jest zgodne ze starym backendem.
   Formularz resetu zacznie działać po wdrożeniu API; w przejściowym oknie
   pokazuje błąd umożliwiający ponowienie.
2. Wdrożyć backend web **i worker** z tej samej wersji. Nie potrzeba migracji,
   nowych zasobów ani nowego sekretu. Pozostają obecne Redis, SMTP i zapisany
   poza hostingiem DJANGO_SECRET_KEY. FRONTEND_URL musi być adresem HTTPS
   panelu, bez query/fragmentu/danych logowania. Nie zmieniać klucza przy tym wdrożeniu.
3. Poczekać na live obu usług, sprawdzić `/health/` = 2.0.11 i rejestrację
   zadania `accounts.tasks.send_password_reset` w workerze. Nie wykonywać
   testu wysyłki w oknie, gdy stary worker nie zna jeszcze nowego zadania.
4. Po zgodzie właściciela wykonać test na wydzielonym koncie i kontrolowanej
   skrzynce: odbiór linku, otwarcie bez zużycia, nowe hasło, odmowa starego
   hasła/tokenów i ponownego użycia linku, nadal wymagane MFA. Nie używać
   rzeczywistego konta klienta ani publikować linku resetującego.
5. Sprawdzić konfigurację MFA hasłem/kodem, anulowanie i błędne hasło.
   Zapisać wynik odbioru w roadmapie. Automatyczne testy używają lokalnego
   SMTP i atrap API; nie dowodzą doręczenia przez produkcyjnego dostawcę.

Rollback: cofnąć web i worker do tej samej poprzedniej wersji, a następnie
panel. Nie ma migracji do odwrócenia. Hasła już zmienione pozostają zmienione,
a odwołane sesje pozostają odwołane. Nie przywracać starej kopii bazy tylko
po to, aby cofnąć ten kod. Niewykonane zadania resetu mogą wygasnąć; po
ponownym uruchomieniu funkcji użytkownik zamawia nowy link.

Podstawa projektu: [OWASP Forgot Password Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html).
