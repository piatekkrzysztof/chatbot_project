# Zmiana hasła i własne sesje

Etap F14/F15/F22, backend 2.0.12. PR poprzedniego etapu #52 jest scalony
(`281a7e0`); potwierdzono web i worker live oraz health 2.0.11. Panel #14
jest scalony (`d8374fa`), Vercel potwierdził wdrożenie. Rzeczywisty odbiór
poczty resetującej pozostaje otwarty; ten etap nie wysyła wiadomości.

## Kontrakt i granice dostępu

| Żądanie pod `/api/accounts/` | Wejście | Wynik |
|---|---|---|
| GET `sessions/?page=1` | JWT własnej aktywnej sesji | `count`, `next`, `previous`, `mfa_enabled`, `results` |
| POST `password-change/` | `current_password`, `new_password`, opcjonalny `kod` | Hasło zmienione, wszystkie poprzednie sesje zakończone |
| POST `sessions/<uuid>/revoke/` | `current_password`, opcjonalny `kod` | Wskazana własna sesja zakończona |
| POST `sessions/revoke-others/` | `current_password`, opcjonalny `kod` | Pozostałe własne sesje zakończone, bieżąca pozostaje |

Pole `kod` jest wymagane przy aktywnym MFA; przyjmuje aktualny TOTP lub
niewykorzystany kod zapasowy. Odpowiedź zapisu ma `detail` oraz
`current_session_revoked`. Nie zwraca tokenów ani nie ustawia/kasuje cookies.
Walidacja hasła jest zgodna z walidatorami Django; spacje są zachowane,
limit to 1024 znaki, a nowe hasło musi różnić się od obecnego.

Lista jest ograniczona do 20 rekordów na stronę. Rekord zawiera tylko `id`,
`created_at`, `expires_at`, `current`. Filtr obejmuje użytkownika, aktywność,
termin i zgodność z hasłem. Nie jest to lista urządzeń: kilka kart może
dzielić sesję, a nie zbieramy lokalizacji, IP ani User-Agent do tego celu.
Porządek: najnowsze logowanie, następnie UUID. Podczas równoczesnych zmian
numerowana paginacja może się przesunąć; przycisk odświeżenia wczytuje od nowa.

Nawet owner/staff/superuser może tu odczytać i zakończyć tylko swoje sesje.
Obca i nieistniejąca sesja zwracają takie samo 404. Publiczny klucz widgetu
nie uwierzytelnia tych operacji. POST wymaga zaufanego Origin/Referer.
Odpowiedzi widoków są no-store/no-referrer. JWT i odciski hasła nie trafiają
do listy ani jej adresów.

## Atomowość i limity

W transakcji blokowany jest wiersz użytkownika, a następnie ponownie
sprawdzane są: aktywność konta, sesja, termin, odcisk hasła i aktualne hasło.
To ta sama blokada, której używają logowanie, refresh i reset. Dopiero po
walidacji nowego hasła zużywany jest kod MFA. Awaria zapisu wycofuje hasło,
zużycie kodu i odwołanie sesji. Zmiana hasła unieważnia także stare linki
resetujące i bilety logowania MFA, bez usuwania konfiguracji MFA.

Zapisy współdzielą limity MFA: 30/IP/5 min, 120 globalnie/min oraz
10 prób/konto/5 min (wspólnie z pozostałymi operacjami MFA). Odczyt listy:
60/IP/min i 600 globalnie/min. Liczniki wymagają istniejącego wspólnego
cache; awaria blokuje operację. Wiarygodność IP za proxy pozostaje osobnym
odbiorem operacyjnym. Nie zmieniamy harmonogramu retencji sesji.

## Panel i równoczesne karty

Przed zapisem panel odświeża sesję, sprawdza czy nie zmieniło się jej ID,
a potem wykonuje pojedynczy POST pod Web Lock. Nie ponawia automatycznie
zapisu po błędzie/utracie odpowiedzi. Limit 20 sekund obejmuje body
odpowiedzi; przy niepewnym wyniku użytkownik otrzymuje informację, że
operacja mogła już zostać wykonana.

Po zakończeniu własnej sesji panel usuwa jej token z pamięci, powiadamia
inne karty i przeładowuje ekran logowania. Nie wysyła dodatkowego logout
ze współdzielonym cookie, który mógłby zakończyć nowsze logowanie. Spóźniona
odpowiedź starej sesji nie usuwa tokenu nowej. Inne przeglądarki otrzymają
odmowę przy kolejnym żądaniu; nie dodajemy serwerowych powiadomień push.
Wiadomość między kartami zawiera tylko ID sesji i ID zdarzenia, nie JWT,
hasło ani kod. Bez Web Locks pozostaje kolejka lokalnej karty i blokady API.

Odczyt sesji i MFA może jawnie się nie udać. Błąd nie jest pokazywany jako
pusta lista lub wyłączone MFA. Formularze są dostępne po poprawnym odczycie,
pozwalają anulować operację, korzystać z menedżera haseł i wkleić kod.
Po zmianie MFA w innym oknie należy odświeżyć listę przed kolejną operacją.

## Wdrożenie i odbiór

1. Wdrożyć backend web i worker 2.0.12; dotychczasowy panel pozostaje zgodny.
   Brak migracji i zmian zmiennych środowiskowych. Obecne sesje nadal działają.
2. Wdrożyć nowy panel, sprawdzić odczyt własnych sesji i stan MFA.
3. Na wydzielonym koncie, po uzgodnieniu testu: otworzyć dwie niezależne
   sesje, zakończyć jedną i sprawdzić odmowę access/refresh; bieżąca ma działać.
   Następnie zmienić hasło z MFA, sprawdzić stare sesje i nowe logowanie.
   Nie zmieniać hasła klienta w ramach testów.
4. Zapisać wynik w roadmapie. Lokalne testy i E2E używają danych syntetycznych
   oraz atrap API; nie zastępują odbioru produkcyjnego.

Rollback: najpierw panel, potem backend web i worker do zgodnych poprzednich
wersji. Nie przywracać bazy: nowe hasła i odwołane sesje zachowują skutki
także w 2.0.11. Ten etap nie zawiera powiadomienia e-mail o zmianie hasła,
procedury odzyskania utraconego MFA ani automatycznego harmonogramu retencji;
te pozycje pozostają otwarte.

Projekt ponownego potwierdzania tożsamości i unieważniania sesji opiera się
na [OWASP Authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
i [OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).
Lokalna walidacja: 110 testów kont/resetu/MFA/sesji oraz 9 testów health,
Ruff w zmienionych plikach, Bandit 0, schemat OpenAPI bez błędów
(jedno wcześniejsze ostrzeżenie PlanEnum), brak nowych migracji. Mypy:
218 wcześniejszych błędów, bez wzrostu i bez wskazań nowego modułu.
