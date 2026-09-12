# F15, część 2: jednorazowa rotacja i wiele kart

Backend 2.0.9 współpracuje z gałęzią panelu `codex/audit-session-rotation`.
Najpierw wdrożyć panel, potem backend. Nie ma migracji bazy ani nowych usług.

Backend weryfikuje podpis/ważność refresh, blokuje rekord konta i w tej samej
transakcji ponownie sprawdza blacklistę, zużywa token i zapisuje jego następcę.
Równoległe żądania z tym samym tokenem nie mogą wydać dwóch nowych sesji.
Awaria zapisu wycofuje również dodanie poprzedniego tokenu do blacklisty.
Konto usunięte lub nieaktywne otrzymuje 401, bez wydania JWT.

## Kontrakt HTTP

- 200: nowy access w JSON i nowy refresh w cookie.
- 409, `code=refresh_conflict`: ważny kryptograficznie token jest już zużyty
  lub unieważniony. Odpowiedź nie ustawia ani nie kasuje cookies. Opóźniona odmowa
  nie niszczy dzięki temu poprawnej sesji innego żądania. Panel ponawia raz,
  z bieżącym cookie przeglądarki; kolejny konflikt kończy próbę odświeżenia.
- 401: brak/nieprawidłowy/wygasły token albo niedostępne konto; cookie kasowane.
- 403: niezaufane źródło, zgodnie z zabezpieczeniami PR #49.

## Panel

Logowanie (także MFA i po zaproszeniu), odświeżanie i wylogowanie korzystają
ze wspólnej blokady Web Locks. Blokada jest współdzielona między kartami tego
samego originu. Oczekiwanie na blokadę jest ograniczone do 30 s, fetch do 20 s.
Szczegóły mechanizmu: [MDN Web Locks](https://developer.mozilla.org/en-US/docs/Web/API/Web_Locks_API).

Wylogowanie czyści pamięć i przekazuje innym kartom wyłącznie losowy znacznik
w localStorage. Nie zapisuje tam JWT, haseł ani danych konta. Pozostałe karty
przechodzą na login, czyszcząc również dane firmy obecne w komponentach.
Spóźniona odpowiedź odświeżania nie nadpisuje nowszego logowania ani wylogowania.

Bez Web Locks pozostaje kolejka w jednej karcie i jednokrotne ponowienie 409;
nie deklarujemy wówczas pełnej koordynacji wszystkich kart. Zablokowany storage
ogranicza powiadomienie o wylogowaniu między kartami. Samo przerwanie fetch
nie gwarantuje, że serwer nie wykonał operacji. Przy awarii sieci może być
konieczne ponowne logowanie; nie wprowadzamy nieskończonego retry.

## Odbiór i dalsze prace

Test PostgreSQL uruchamia dwa równoległe żądania; oczekuje 200/409 i działającego
tokenu zwycięzcy. Sprawdzamy replay, rollback po awarii i niedostępne konta.
Test panelu w Chrome otwiera dwie karty z prawdziwym Web Locks; backend w tym
teście jest atrapą. Oddzielne testy sprawdzają opóźnioną odpowiedź i zmianę konta.

Po wdrożeniu: ponownie otworzyć panel w dwóch kartach, odświeżyć obie i wylogować
się z jednej. Sprawdzić zakończenie sesji UI w obu kartach i health 2.0.9.

Otwarte pozostają: odwoływanie całej rodziny tokenów i access JWT, unieważnianie
po zmianie hasła, odzyskiwanie konta, świeże hasło przed konfiguracją MFA.
Dotychczasowy access JWT może działać do upływu 15 minut; ta część nie dodaje
serwerowego mechanizmu natychmiastowego odwołania wszystkich sesji.
