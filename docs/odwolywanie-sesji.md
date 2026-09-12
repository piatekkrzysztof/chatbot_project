# Odwoływanie sesji — F15, część 3

## Zachowanie

Każde udane logowanie (także z MFA) tworzy osobną sesję w PostgreSQL.
Refresh i access JWT niosą jej losowy identyfikator `sid`. Kolejne rotacje
zachowują tę samą sesję i nie przedłużają jej końca: po 14 dniach od logowania
trzeba ponownie podać dane. Access zachowuje limit 15 minut, skrócony w razie
potrzeby do końca sesji.

Każde uwierzytelnienie JWT sprawdza właściciela, datę końca, odwołanie sesji
i zgodność z aktualnym hasłem konta. Sprawdzenie działa w middleware tenanta
oraz niezależnie w DRF. Brak rekordu lub `sid` oznacza odmowę, nigdy automatyczne
utworzenie sesji. Nie ma cache'u odwołań, który opóźniałby wylogowanie.

Logout odwołuje całą sesję, również gdy przeglądarka przesłała starszy,
już obrócony refresh. Podpis i termin tokenu są nadal sprawdzane. Inne logowania
tego samego użytkownika i inne konta pozostają dostępne. Ponowiony logout daje 204.
Odwołana sesja daje 401; konflikt rotacji w aktywnej sesji nadal daje 409 bez
kasowania cookie, zgodnie z panelem #13.

Rotacja i logout korzystają z tej samej blokady wiersza użytkownika. Jeśli
rotacja wygra wyścig, logout odwoła także wydanego potomka. Jeśli wygra logout,
rotacja nie wyda tokenów. Błąd zapisu sesji podczas logowania wycofuje także JWT;
dotychczasowa transakcja MFA wycofuje również zużycie kodu i biletu.

Zmiana zapisanego hasła unieważnia poprzednie sesje bez zależności od sygnałów
Django: także po `QuerySet.update(password=...)`. W bazie sesji zapisany jest
HMAC z `user.get_session_auth_hash()`, nie hasło ani jego wartość z tabeli kont.
Fingerprint nie trafia do JWT, odpowiedzi HTTP ani dzienników. Zmiana głównego
`DJANGO_SECRET_KEY` również zakończy sesje; operacyjna rotacja tego klucza
wymaga uwzględnienia szyfrowania MFA.

Odwołanie blokuje kolejne sprawdzenia uwierzytelnienia po zatwierdzeniu logout.
Nie anuluje operacji, która została już wcześniej uwierzytelniona. Brak sieci
podczas logout może uniemożliwić dotarcie żądania do serwera.

## Wdrożenie

1. Panel #13 jest wymagany dla dotychczasowej obsługi 409; jego produkcyjne
   wdrożenie na `7c6cd5b` potwierdzono 12.09.2026. Backend #50 i worker
   działają na `c16a52d`, wersja 2.0.9.
2. Po zielonym CI scalić ten PR. Zwykły build Rendera wykonuje migrację
   `accounts.0036_login_session`: dodaje wyłącznie tabelę sesji i indeksy.
   Nie zmienia kont, dokumentów, MFA ani danych firm. Nie wymaga nowych usług
   lub zmiennych środowiskowych.
3. Poczekać na zakończenie wdrożenia web i workera. Sprawdzić `/health/`
   (2.0.10). **Wszyscy dotychczas zalogowani muszą zalogować się ponownie**:
   dotychczasowe JWT nie mają `sid`. Podczas przełączania starych instancji
   na nowe obowiązują jeszcze zasady uruchomionej wersji.
4. Na koncie testowym sprawdzić login, refresh, MFA i logout oraz odmowę
   użycia zapisanego wcześniej access JWT po logout. Oddzielna sesja na innym
   urządzeniu powinna dalej działać. Nie zapisywać wartości tokenów w raportach.

Preferowana reakcja na problem to poprawka nowej wersji. Powrót do poprzedniego
kodu przywraca słabsze sprawdzanie JWT i może ponownie dopuścić tokeny odwołane
przez nową wersję. Samo cofnięcie migracji nie jest bezpiecznym planem wycofania;
usuwa też rejestr odwołań. Tabela może pozostać podczas analizowania awarii.

## Koszt, retencja i ograniczenia

- Jeden wiersz na logowanie, nie na każde odświeżenie. Rotacje nadal korzystają
  z istniejącej tabeli tokenów SimpleJWT. Każde sprawdzenie JWT dodaje odczyt sesji
  po kluczu głównym; middleware i DRF sprawdzają ją niezależnie. Pomiar pod
  obciążeniem pozostaje częścią F16.
- `python manage.py purge_login_sessions --dry-run` pokazuje liczbę sesji
  wygasłych co najmniej 24 godziny temu; bez flagi usuwa je partiami po 1000.
  Nie usuwa kont ani innych danych. Brak wpisu oznacza odmowę dostępu.
  Komendę trzeba włączyć do istniejącego harmonogramu wraz z
  `flushexpiredtokens`; ten PR nie zmienia konfiguracji produkcji.
- Utrata połączenia z bazą nie może prowadzić do uwierzytelnienia JWT.
  To zwiększa zależność dostępności panelu od bazy, którą aplikacja już wykorzystuje.
- Dezaktywowane konto jest odrzucane. Ponowna aktywacja konta z niezmienionym
  hasłem nie jest operacją odwołania wszystkich sesji; osobny interfejs do
  zarządzania urządzeniami i awaryjnego odwołania wszystkich sesji pozostaje otwarty.
- Ten etap nie dodaje formularza zmiany/resetu hasła, odzyskiwania MFA ani
  wymagania świeżego hasła przed jego konfiguracją. Kolejny etap kont obejmuje
  te przepływy i rzeczywisty odbiór poczty.

Wykorzystana biblioteka domyślnie blokuje tokeny refresh, a nie access:
[dokumentacja blacklist SimpleJWT](https://django-rest-framework-simplejwt.readthedocs.io/en/stable/blacklist_app.html).
Dlatego samo dotychczasowe `blacklist()` nie kończyło dostępu do API.
