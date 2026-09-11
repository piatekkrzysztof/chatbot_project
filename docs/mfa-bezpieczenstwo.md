# MFA — wdrożenie i obsługa

Etap F14, wersja 2.0.7. Wymagany PostgreSQL i wspólny cache Redis.
Nie dodaje usług ani abonamentów.

## Zachowanie

- Django admin wymaga hasła oraz TOTP lub kodu zapasowego. Samo hasło, stara
  sesja bez MFA i bezpośredni adres modelu nie dają dostępu. Wyłączenie lub
  ponowna konfiguracja MFA unieważnia uprawnienie zapisane w sesji admina.
- Pierwszy krok logowania API nie tworzy JWT dla konta z MFA. Bilet jest
  jednorazowy, ważny pięć minut, z maksymalnie pięcioma błędnymi kodami.
  Zmiana hasła, wyłączenie konta lub zmiana MFA unieważnia bilet.
- TOTP i kody zapasowe są zużywane atomowo. Wydanie JWT i zużycie biletu/kodu
  są jedną transakcją: awaria zapisu tokena pozwala ponowić próbę.
- MFA ogranicza próby per IP, globalnie i per konto. Limit konta obejmuje
  API, admin oraz konfigurację; awaria cache blokuje weryfikację.
- Sekrety TOTP są szyfrowane uwierzytelnionym Fernet, także w eksporcie
  Django. Kody zapasowe pozostają skrótami. Klucz MFA wyprowadzany jest
  przez HKDF-SHA256 z DJANGO_SECRET_KEY, z osobnym kontekstem MFA.
  To ochrona przed samym wyciekiem bazy; dostęp do bazy i sekretu aplikacji
  pozwala odszyfrować dane. Nie zastępuje niezależnego BACKUP_ENCRYPTION_KEY.

## Przed wdrożeniem

1. Zabezpiecz DJANGO_SECRET_KEY poza Renderem. Jest teraz potrzebny także
   do odtworzenia MFA z kopii bazy. Nie zapisuj jego wartości w zgłoszeniach
   ani logach. BACKUP_ENCRYPTION_KEY nie zastępuje tego klucza.
2. Osoby korzystające z Django admina muszą wcześniej włączyć MFA w panelu
   aplikacji i zapisać kody zapasowe. Nowe konto staff powinno mieć przypisaną
   firmę, aby mogło przejść konfigurację w panelu. Kontrola read-only z
   11.09.2026 wykazała zero aktywnych kont staff; sprawdź ponownie, jeśli
   utworzono administratora po tej kontroli.
3. Wykonaj aktualną szyfrowaną kopię. Przećwicz migrację i rollback na jej
   izolowanej kopii, z właściwym kluczem aplikacji.
4. Zaplanuj krótkie okno serwisowe i zatrzymaj przyjmowanie ruchu oraz stare
   procesy aplikacji przed migracją. Migracja 0035 zmienia istniejące sekrety
   na szyfrogramy, których poprzedni kod nie rozumie. Sam rolling deploy
   ze starymi procesami w trakcie migracji nie jest bezpiecznym wdrożeniem.
5. Uruchom migracje nową wersją i uruchom web oraz worker z tym samym kodem
   i DJANGO_SECRET_KEY. Zweryfikuj logowanie bez MFA, z MFA, zapasowym kodem,
   admin oraz odrzucenie powtórzonego biletu. Dopiero potem przywróć ruch.

Trwające bilety MFA ze starej wersji tracą ważność: należy ponownie podać
hasło. Nie zmienia się konfiguracja aplikacji uwierzytelniającej użytkownika.
Ten PR nie zmienia kontraktu konfiguracji MFA w panelu.

## Rotacja i odzyskiwanie

Przy rotacji ustaw nowy DJANGO_SECRET_KEY i zachowaj poprzedni w
DJANGO_SECRET_KEY_FALLBACKS (lista rozdzielona przecinkami). Ustawienia muszą
być spójne na webie, workerze i procesach administracyjnych. Następnie:

    python manage.py rotate_mfa_secrets --dry-run
    python manage.py rotate_mfa_secrets

Polecenia podają tylko liczbę rekordów; nie ujawniają kluczy ani sekretów.
Każdy rekord jest przepisany pod blokadą, bez nadpisania równoległej zmiany
konfiguracji. Po sprawdzeniu logowania usuń stary klucz z aktywnych fallbacks,
ale zachowaj jego bezpieczną kopię przez cały okres przechowywania backupów
zaszyfrowanych poprzednim kluczem. Rotacja unieważnia bilety i dowód MFA
w istniejących sesjach admina; wymagane jest ponowne logowanie.

Brak właściwego klucza lub uszkodzony szyfrogram zatrzymują odczyt MFA.
Nie ma automatycznego przejścia na jawny sekret ani logowania samym hasłem.
W razie utraty telefonu użyj kodu zapasowego. Brak telefonu i kodów wymaga
zweryfikowanej procedury odzyskania konta; nie usuwaj MFA na podstawie samej
wiadomości e-mail. Pełna procedura odzyskiwania pozostaje kolejnym etapem.

Rollback: zatrzymaj ruch i procesy, używając nadal nowego kodu wykonaj
`python manage.py migrate accounts 0034_pending_registration`, a dopiero
potem uruchom poprzedni kod. Odwrócenie przywraca jawne sekrety w bazie
i usuwa wyzwania MFA; wymaga właściwego klucza. Nie cofaj samego obrazu
aplikacji przy pozostawieniu zaszyfrowanych rekordów.

## Retencja i pozostały odbiór

    python manage.py purge_mfa_challenges --dry-run
    python manage.py purge_mfa_challenges

Polecenie usuwa wyłącznie bilety wygasłe od ponad 24 godzin. Należy podłączyć
je do istniejącego harmonogramu z kontrolą braku przebiegów. Ten PR dostarcza
komendę; nie uruchamia harmonogramu na produkcji.

Nadal do wykonania: świeże potwierdzenie hasła przed konfiguracją MFA
(wspólny kontrakt panel/API), reset hasła, unieważnianie sesji API,
cookie/CSRF oraz operacyjny odbiór kopii i odzyskiwania konta.

Mechanizmy bazują na [Fernet/MultiFernet](https://cryptography.io/en/latest/fernet/)
i [sesjach Django](https://docs.djangoproject.com/en/5.2/topics/auth/default/#session-invalidation-on-password-change).
