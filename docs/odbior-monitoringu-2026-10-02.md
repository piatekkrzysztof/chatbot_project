# Wdrożenie i odbiór monitoringu — PR #116

Stan zaktualizowany 2.10.2026. Kod i bieżące przebiegi potwierdzone na produkcji
1.10.2026. Po użyciu Test Notification właściciel potwierdził 2.10 odbiór
wiadomości „monitor is down”, a następnie „monitor is up” na uzgodnionej
skrzynce Gmail. Doręczenie powiadomień testowych zaliczone. 2.10 zaliczono lokalne zatrzymanie workera na ponad 180 s i restart Redis.
[Dowody oraz pozostały zakres](odbior-a04-awarie-2026-10-02.md). Zewnętrzne
wykrycie rzeczywistej awarii przez UptimeRobot pozostaje otwarte.

## 1. Scalenie i automatyczne wdrożenia

- PR #116: MERGED, commit `faaf384baaa691dcea249aa74a7c264105435f0a`.
- Web: `srv-cvd926tumphs73ea9uc0`, wdrożenie `dep-dav5p1lg1s2s73dcrnsg`.
- Worker: `srv-d9vha261egvs73e88it0`, wdrożenie `dep-dav5p1lg1s2s73dcroj0`.
- Oba uruchomione automatycznie przez scalenie około 15:13; zakończone sukcesem.
- Web: migracja `accounts.0045_przebieg_monitora... OK` o 15:14:30,
  komunikat „Your service is live” o 15:15:36, następnie status Deploy succeeded / Live.
- Worker: instancja `gd5td`, concurrency=1, zadanie monitorujące zarejestrowane;
  Beat start 15:15:09.748, worker ready 15:15:11.399.
- Nie uruchamiano ręcznego deployu, nie zmieniano konfiguracji ani danych klientów.

## 2. Rzeczywisty łańcuch Beat → broker → worker → baza → web

Pierwszy odczyt po scaleniu pokazywał jeszcze wersję 2.19.7.
Około 15:15:56, już po wdrożeniu 2.19.8, publiczny health pokazywał:
`status=ok`, `stan=ograniczony`, `baza=true`, `broker=true`, `zadania=false`.
Był to prawidłowy brak pierwszego potwierdzenia, a nie ręcznie wywołana awaria.

Potwierdzone przebiegi `accounts.tasks_monitoring.potwierdz_przebieg`:

| Próba | Publikacja Beat | Sukces workera | Czas wykonania |
|---|---|---|---|
| `eb783183-535f-4974-8253-8fa41ee4be28` | 15:16:09.849 | 15:16:10.596 | 0.733 s |
| `a5751e06-381c-4c6d-8ba0-68aac3d889cf` | kolejny cykl minutowy | 15:17:11.195 | 1.338 s |

Po pierwszej próbie health przeszedł do `zadania=true`, `stan=ok`.
Końcowy odczyt z 15:19:14 CEST: HTTP 200, wersja 2.19.8, baza=true,
broker=true, zadania=true, stan=ok.
Nagłówek: `Cache-Control: no-store, must-revalidate, no-cache, max-age=0, private`.

Nie zatrzymywano produkcyjnego workera, Beat ani brokera. Powyższe dowodzi
działania świeżej próby i odczytu przez web; nie jest testem utraty procesu
przez ponad 180 sekund ani testem wszystkich zadań biznesowych.

## 3. Faktyczna konfiguracja UptimeRobot

Po zalogowaniu przez użytkownika odczytano istniejący monitor 804109286:

- Adres: `https://api.agencjasm-art.pl/health/`.
- Typ: Keyword; fraza dokładnie `"stan": "ok"`.
- Warunek: „Start incident when keyword does not exist”.
- Częstotliwość: 5 minut; timeout żądania: 30 sekund.
- Powiadomienia e-mail włączone dla `krzysztofpiatek2020@gmail.com`.
- Ustawienie wiadomości: „No delay, no repeat”.
- Stan przy odczycie: Up. Nie zapisano żadnych zmian konfiguracji.

To osobna lista odbiorców od EMAIL_ALERTOW aplikacji. Nie ma tu potwierdzenia
powiadamiania drugiej skrzynki firmowej. Starsza propozycja „dwa nieudane
sprawdzenia / do 13 minut” jest wariantem z dokumentacji, a nie dowodem
bieżącego progu: panel pokazuje brak opóźnienia. Rzeczywisty czas alarmu
obejmuje ważność próby 180 s, cykl monitora 5 min, ewentualną weryfikację
dostawcy i doręczenie. Nie zmierzono go w tej sesji.

## 4. Otwarte kroki

1. **Zakończone 2.10:** Test Notification oraz odbiór na Gmailu obu wiadomości
   (down, następnie up) potwierdzone przez właściciela.
2. Oddzielnie przeprowadzić kontrolowaną próbę wykrycia braku frazy na celu
   testowym oraz w izolacji zatrzymania Beat/workera, wygaśnięcia znacznika
   i odzyskania. Nie zmieniać produkcyjnego health ani nie zatrzymywać usług.
3. Odbiór wcześniejszego alarmu aplikacji nr 22 (PR #115) na obu skrzynkach
   nadal bez potwierdzenia w rozmowie.
4. **Zakończone 2.10 w zakresie syntetycznym:** awarie magazynu/brokera
   i procesów oraz odtworzenie kopii 2.19.8 z kwarantanną zleceń. Dalej A01/A02 Stripe test mode,
   A03/A05 panel/widget/API i bramki komercyjne z roadmapy.

## 5. Zaobserwowany problem rozliczeniowy

Render wyświetlił „Payment failed” i wezwanie do aktualizacji karty,
aby uniknąć utraty dostępu do usług workspace. Powiadomiono właściciela
z linkiem do rozliczeń. Nie podejmowano działań płatniczych i nie określono
terminu ewentualnego ograniczenia usług — panel go nie pokazywał.

## Test powiadomienia — 2.10.2026
Użytkownik zatwierdził wysyłkę testową. Przed wysłaniem ponownie odczytano w monitorze 804109286 włączony e-mail krzysztofpiatek2020@gmail.com; SMS, voice i push nieaktywne. W oknie testu odznaczono dodatkowych notify-only users oraz integracje (0). Kliknięto Send test notifications dokładnie raz; panel potwierdził „Test notification sent”. Nie zmieniano zapisanej konfiguracji monitora. Właściciel potwierdził odbiór dwóch wiadomości: najpierw „monitor is down”, następnie „monitor is up”. Jeden wywołany test wygenerował zatem parę powiadomień, zamiast zapowiedzianej pojedynczej wiadomości. Test przycisku powiadomień nie jest próbą wykrycia rzeczywistej awarii celu i nie potwierdza doręczenia wcześniejszego alarmu aplikacji nr 22.
