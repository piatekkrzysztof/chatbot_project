# A04 — odbiór awarii i odtworzenia, 2.10.2026

## Wynik i zakres

Próby opisane poniżej zakończyły się sukcesem na kodzie 2.19.8, po scaleniu
PR #116 (`faaf384baaa691dcea249aa74a7c264105435f0a`). Nie znaleziono w tych
scenariuszach nowego błędu kodu produkcyjnego. Dodano sześć powtarzalnych
przypadków regresji; pozostałe zmiany dotyczą dowodów i roadmapy.

Środowisko: Windows, Python 3.12, PostgreSQL 16.15 z pgvector, syntetyczne
bazy `test_saas_restore_*`, lokalne katalogi plików. Do dodatkowej próby
operacyjnej użyto osobnego Redis 7 i osobnego procesu Celery solo,
concurrency=1. Baza i Redis udostępnione tylko na 127.0.0.1, na portach
15440 i 16389. Nie dotykano usług produkcyjnych, R2, Stripe ani danych
klientów; nie wysyłano e-maili. Zegara systemowego nie zmieniano.

## 1. Granice transakcji i utrata procesu

Powtarzalne testy: `documents/tests/test_awarie_procesu.py`.
Proces pomocniczy: `documents/tests/awaria_procesu.py`.

| Scenariusz | Wykonana awaria | Potwierdzony wynik |
|---|---|---|
| Utrata callbacku | Twarde zakończenie osobnego procesu po zatwierdzeniu usunięcia rekordu, przed publikacją callbacku | Dokument usunięty, bajty nadal istnieją, trwałe zlecenie `oczekuje`; obchód wykonany przez worker usuwa plik w pierwszej próbie |
| Przerwanie przed DELETE | Zakończenie procesu po zatwierdzeniu dzierżawy, przed usunięciem bajtów | Stan `praca`, jedna próba; aktywna dzierżawa blokuje przejęcie; po jej wygaśnięciu nowy token i skuteczna druga próba |
| Przerwanie po DELETE | Zakończenie procesu po usunięciu bajtów, przed zapisem sukcesu | Rejestr nadal `praca`; powtórzenie toleruje brak pliku i kończy zlecenie |
| Broker nie przyjmuje połączenia | Rzeczywiste TCP ECONNREFUSED na zarezerwowanym lokalnym porcie | Brak synchronicznego kasowania, trwałe zlecenie zachowane; obchód po wznowieniu kolejki usuwa bajty |
| Błąd magazynu | Lokalny serwer HTTP zwraca 503 na DELETE rzeczywistego klienta S3, następnie 204 | Dwie próby HTTP w pierwszym podejściu (jedno ponowienie SDK), zachowane zlecenie i odroczenie; po odzyskaniu kolejna próba kończy się sukcesem |

W próbach zabicia procesu punkt przerwania jest instrumentowany. Sam proces
jest rzeczywiście kończony (`TerminateProcess` na Windows, `SIGKILL` w Linux),
więc kod sprzątania w dziecku nie wykonuje się. Zapis PostgreSQL i operacje
plikowe są rzeczywiste. Dziesięciominutową dzierżawę przyspieszono zmianą jej
terminu w testowym wierszu; najpierw sprawdzono odmowę przejęcia przed terminem.
Obchód odzyskujący przechodzi przez transport Kombu w pamięci i worker Celery.
Serwer HTTP symuluje odpowiedzi S3; nie jest emulatorem całego R2.

## 2. Rzeczywisty worker i restart brokera

Dodatkową próbę wykonano poza pytest, na oddzielnej syntetycznej bazie.
Zdarzenia z odczytami health: [zapis JSON](odbior-a04-awarie-2026-10-02.json).
Poniższe godziny są w Europe/Warsaw (CEST); plik JSON używa UTC.

1. **10:53:58:** publikacja przez Scheduler Beat, przejście przez lokalny Redis,
   zapis osobnego workera do PostgreSQL; health: HTTP 200, wszystkie trzy
   składowe true, `stan=ok`.
2. **10:53:58:** twarde zakończenie procesu workera. Redis i baza działają.
3. **10:56:55:** rzeczywisty wiek ostatniej publikacji 181,588 s, bez zmiany
   zegara ani znacznika w bazie. Health: HTTP 200, baza=true, broker=true,
   zadania=false, `stan=ograniczony`.
4. **10:56:59:** nowy proces workera i świeża publikacja Scheduler Beat;
   health ponownie `stan=ok`.
5. **10:57:02:** po zatrzymaniu wyłącznie testowego Redisa health pokazuje
   broker=false i `stan=ograniczony`; HTTP pozostaje 200.
6. **10:57:14:** usunięcie syntetycznego dokumentu przy niedostępnym brokerze
   zachowuje zlecenie `oczekuje`, próby=0.
7. **10:57:15:** po uruchomieniu Redisa istniejący worker sam odzyskuje
   połączenie. Odbiera opublikowany obchód, kończy zlecenie w pierwszej próbie
   oraz zapisuje świeżą próbę monitorującą. Health ponownie `stan=ok`.

To próba ścieżki Scheduler → Redis → worker → DB → funkcja health, nie pełny
serwer HTTP za proxy Rendera. Publikacje Scheduler wywołano jawnie; nie
uruchamiano osobnego demona Beat pracującego co minutę podczas przerwy.
Pozostaje oddzielny scenariusz zatrzymania tylko Beat oraz niezależny test
wykrycia braku słowa kluczowego przez UptimeRobot na celu testowym.
Nie mierzono czasu doręczenia zewnętrznego alarmu podczas rzeczywistej awarii.

## 3. Pełna kopia i zabezpieczone odtworzenie

Nowy przypadek w `accounts/tests/test_full_backups.py`:
`test_full_restore_quarantines_every_unfinished_state_and_preserves_files`.

1. Utworzono syntetycznego użytkownika, firmę, dokument i logo współdzielone
   z awatarem oraz sześć zleceń: oczekuje, praca, blad, wstrzymane, gotowe,
   zachowany. Każdy wpis miał odpowiadający mu plik źródłowy.
2. Wykonano `backup_full --source-quiesced`, zweryfikowano manifest i wersje.
   Źródło było testowe, bez równoległych procesów zapisujących.
3. Opróżniono wyłącznie bazę testu; uruchomiono `restore_full_backup` do
   pustego lokalnego celu i nowego katalogu. Komenda zachowała swoje kontrole
   wersji aplikacji, PostgreSQL, migracji, klucza i pustego celu.
4. Zweryfikowano relację dokument–firma, poprawne hasło użytkownika oraz
   SHA-256 obu plików z manifestu. Kopia obejmuje pliki mające odwołania,
   nie bajty obiektów wskazanych jedynie przez rejestr usuwania.
5. Wszystkie cztery niedokończone stany zmieniły się na `wstrzymane`,
   kod `odtworzona_kopia`; zmienił się token, wyczyszczono dzierżawę i alarm.
   Dwa zakończone stany zachowały swój stan i token.
6. Po przywróceniu konfiguracji magazynu źródłowego wywołano obchód.
   Żaden z sześciu plików źródłowych nie został usunięty.

Pomiar tej małej próbki: zaszyfrowana kopia **14 866 B**, dwa pliki w manifeście,
utworzenie i weryfikacja **0,110 s**, odtworzenie **0,140 s**.
Wersja aplikacji 2.19.8, PostgreSQL 16.15. To pomiar mechanizmu na syntetycznej
próbce, **nie RTO produkcji ani nowa kopia danych produkcyjnych**.
Szerszy zestaw istniejących testów obejmuje również MFA, uprawnienia, wektory,
izolację firm i odrzucanie uszkodzonych lub niezgodnych kopii.

## 4. Wyniki automatyczne i odtworzenie prób

- Nowe próby procesów/TCP/HTTP: **5 passed**, 46,92 s.
- Usuwanie, pełne kopie i monitoring, razem z nowym testem odtwarzania:
  **95 passed**, 98,06 s.
- Łącznie **100 zaliczonych przypadków**, w tym sześć nowych. Ruff: bez błędów.
- Wynik kompletnego CI dla końcowego commita należy sprawdzić w PR; wyniki
  lokalne nie są jego zastępstwem.

Uruchomienie powtarzalnej części wymaga PostgreSQL z pgvector i izolowanej
konfiguracji Django. Nazwa bazy źródłowej `saas_restore_*` sprawia, że pytest
tworzy cel `test_saas_restore_*`. Proces pomocniczy odmawia innej nazwy lub
zdalnego hosta, nie ładuje `.env`, dopuszcza połączenia Python tylko z loopback
i używa syntetycznych ustawień usług. Nie uruchamiać z konfiguracją produkcyjną.

```text
pytest -q documents/tests/test_awarie_procesu.py documents/tests/test_trwale_usuwanie.py accounts/tests/test_full_backups.py accounts/tests/test_monitoring_zadan.py
```

## 5. Co pozostaje otwarte

1. Potwierdzenie odbioru alarmu aplikacji nr 22 na obu uzgodnionych skrzynkach.
   Odbiór powiadomień UptimeRobot nie potwierdza tego e-maila.
2. Wykrycie rzeczywistej zmiany słowa kluczowego na celu testowym przez
   UptimeRobot, z pomiarem doręczenia i powrotu; osobna próba zatrzymania Beat.
3. Aktualna kopia produkcji i odtworzenie jej zgodną wersją, jeśli wymagamy
   odświeżenia produkcyjnego odbioru z 17.09. Dzisiejsza próba zamyka regresję
   mechanizmu A04, nie aktualność produkcyjnego archiwum ani RPO/RTO.
4. **Następny etap kodu i odbiorów: A01/A02 w Stripe test mode** — podwójny
   zakup, utracona odpowiedź, kolejność zdarzeń i uzgadnianie. Dalej A03/A05,
   przepływy użytkownika, wydajność i pozostałe bramki komercyjne z roadmapy.
