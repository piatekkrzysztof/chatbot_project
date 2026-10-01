# Odbiorcy alarmów operatora

Od 2.19.7 `EMAIL_ALERTOW` zawiera jeden adres lub listę adresów oddzielonych
przecinkami. `DEFAULT_FROM_EMAIL` służy wyłącznie jako nadawca i nie jest
domyślnym odbiorcą. Nie zakładaj, że adres nadawcy ma istniejącą skrzynkę.

```dotenv
EMAIL_ALERTOW=operator@example.com,backup-operator@example.com
DEFAULT_FROM_EMAIL=powiadomienia@example.com
```

Spacje przy adresach są pomijane, powtórzenia usuwane z zachowaniem
kolejności. Wpisuj same adresy, bez nazw wyświetlanych. Nie używaj średników.
Błędny adres, pusty element lub znak nowej linii odrzuca całą listę,
bez wysyłki do części odbiorców i bez fallbacku. Pusta konfiguracja zgłasza
błąd. Walidacja składni nie dowodzi istnienia skrzynki ani doręczenia.

## Wdrożenie istniejącej instalacji

1. Uzgodnij rzeczywistych odbiorców z właścicielem. Ustawienie dotyczy
   alarmów technicznych, w tym odmów widgetu, ciszy, bazy, próbnych kont,
   rezerwacji AI, uzgadniania Stripe i trwałego usuwania plików.
2. Wdrożenie kodu i konfiguracji zaplanuj razem. Kod do 2.19.6 obsługuje
   tylko pojedynczy adres; nie wdrażaj na nim listy z przecinkami.
   Jeżeli konfigurację trzeba wprowadzić przed aktualizacją kodu, ustaw
   tymczasowo jeden uzgodniony adres. Po wdrożeniu 2.19.7 ustaw pełną listę.
3. Ustaw `EMAIL_ALERTOW` na web i workerze. Render trzyma konfiguracje usług
   osobno. Zastosuj je przez wdrożenie/restart; nie zmieniaj nadawcy,
   loginu ani hasła SMTP, jeżeli ich zmiana nie jest potrzebna.
4. Sprawdź działanie workera, Beat oraz odczyt faktycznej listy odbiorców
   bez wypisywania pozostałych zmiennych środowiskowych i sekretów.
5. Wyślij jedną uzgodnioną wiadomość testową i potwierdź odbiór na każdej
   skrzynce. Sam sukces `send_mail`, znacznik w bazie lub przyjęcie przez
   SMTP nie potwierdzają doręczenia wszystkim adresatom.

Nie wpisuj listy odbiorców do `DEFAULT_FROM_EMAIL`. Dokładne adresy właściciela
pozostają w konfiguracji środowiskowej, nie w repozytorium.
