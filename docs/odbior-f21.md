# Odbiór F21: kopia, odtworzenie i alarmy

Stan na 17.09.2026, wersja 2.9.0. Protokół odbioru dla właściciela. Kod kopii
i odtwarzania jest gotowy od 2.0.14 ([opis formatu](pelna-kopia-i-odtworzenie.md));
ten dokument dokłada brakujące kontrole i prowadzi przez odbiór krok po kroku.

Trzy warunki zamknięcia F21, wprost z [roadmapy](roadmapa-po-audycie.md):

1. rzeczywista kompletna kopia produkcji i jej **izolowane** odtworzenie na PostgreSQL 16,
2. **zmierzone** RPO i RTO, a nie zadeklarowane,
3. działający harmonogram i alarmy - **także przy braku przebiegu**.

Zielone CI na danych syntetycznych żadnego z nich nie zamyka.

## Co dokłada 2.9.0

| Polecenie | Co sprawdza | Gdzie ma chodzić | Potrzebuje klucza |
|---|---|---|---|
| `check_backup` (było) | treść i wiek najnowszej kopii dziennej | Render | tak |
| `kontrola_pelnej_kopii` (nowe) | treść, komplet i wiek najnowszej **pełnej** kopii | Render albo Twoja maszyna | tak |
| `kontrola_obecnosci_kopii` (nowe) | czy w magazynie w ogóle coś przybywa | **poza Renderem** | nie |

Pełna kopia (`backup_full`, format `.saas`) nie miała dotąd kontroli, która sama
znajdzie najnowszą: `verify_full_backup` wymaga podania nazwy pliku, więc nadaje
się do sprawdzenia konkretnej kopii, a nie do harmonogramu.

Trzecia kontrola istnieje dlatego, że kontrola uruchamiana na Renderze nie wykryje
awarii Rendera ani zatrzymania harmonogramu - milczy wtedy dokładnie tak samo,
jak przy spokoju. Działa bez klucza szyfrowania, żeby klucz odszyfrowujący
wszystkie kopie nie musiał trafiać do sekretów repozytorium. Odpowiada tylko na
pytanie „czy coś nowego się pojawiło"; treści pilnują dwie pozostałe.

Przebieg GitHub Actions: [`.github/workflows/kontrola-kopii.yml`](../.github/workflows/kontrola-kopii.yml),
na razie wyłącznie ręczny - harmonogram jest zakomentowany do czasu dodania sekretów.

## Zanim zaczniesz

- **Pełna kopia wymaga wstrzymania zapisów.** R2 i PostgreSQL nie mają wspólnej
  migawki, więc `backup_full` żąda flagi `--source-quiesced`, która jest Twoim
  oświadczeniem, a nie mechanizmem. To znaczy kilka minut przerwy w działaniu
  widgetu i panelu. Wybierz porę poza godzinami pracy klientów.
- **Nic nie kasujemy.** Ten odbiór niczego nie usuwa z produkcji ani z archiwum
  kopii. Retencja kopii i automatyczne usuwanie danych wchodzą dopiero po nim.
- **Sekrety wpisujesz Ty.** Wartości kluczy i tokenów nie należą do tego
  dokumentu ani do repozytorium.

## Krok A: pełna kopia produkcji

1. Zapisz porę rozpoczęcia okna.
2. Wstrzymaj zapisy: w panelu Rendera zatrzymaj (suspend) usługę web i worker
   (oraz beat, jeśli chodzi osobno). Poczekaj, aż trwające zadania się skończą.
   Nie uruchamiaj w tym czasie migracji ani ręcznych zmian w R2.
3. W powłoce usługi web (Render → Shell) uruchom:

```bash
python manage.py backup_full --source-quiesced --to-storage
```

4. Zapisz wypisaną nazwę kopii, liczbę plików i bajtów oraz porę zakończenia.
5. Wznów usługi. **Zapisz długość okna** - to jest realny koszt pełnej kopii.
6. Sprawdź kopię, nie ruszając produkcji:

```bash
python manage.py kontrola_pelnej_kopii
```

Wynik to JSON z nazwą, czasem snapshotu, liczbą plików i bajtów. Niezerowy kod
wyjścia znaczy, że kopii nie ma albo nie da się jej odczytać - wtedy przerwij
odbiór i zgłoś wynik, zamiast powtarzać okno.

## Krok B: izolowane odtworzenie

Odtwarzamy **na Twojej maszynie**, nie na Renderze. Pełna instrukcja z
uzasadnieniem każdego ograniczenia jest w
[pełnej kopii i odtworzeniu](pelna-kopia-i-odtworzenie.md#próba-odtworzenia--nowa-lokalna-baza);
tu skrót kolejności:

1. Pobierz kopię z R2 do prywatnego katalogu.
2. Przygotuj pustą bazę **PostgreSQL 16 z pgvector**, nazwaną `saas_restore_<cokolwiek>`.
   Polecenie odmawia pracy na innej nazwie, na zdalnym adresie i na Renderze.
3. Uruchom proces bez produkcyjnego `.env`: ustaw `PYTHON_DOTENV_DISABLED=1`
   i podaj wyłącznie adres lokalnej bazy, `BACKUP_ENCRYPTION_KEY` oraz oryginalny
   `DJANGO_SECRET_KEY`. **Nie podawaj** Stripe, OpenAI, poczty ani dostępu do R2.
4. `python manage.py migrate`, potem:

```bash
python manage.py restore_full_backup /prywatny/kopia.saas --output /prywatny/nowe-odtworzenie
```

Kod odtwarzania sam blokuje sieć i pocztę w swoim procesie, ale to dodatkowa
zapora, nie zamiennik izolacji środowiska.

## Krok C: co sprawdzić na odtworzonej bazie

Na jednej, wybranej firmie - najlepiej Twojej własnej, nie klienta:

| Sprawdzenie | Czego dowodzi |
|---|---|
| Logowanie i drugi składnik | hasła i sekrety MFA przeżyły kopię |
| Role: właściciel, pracownik, podgląd | uprawnienia nie zgubiły się po drodze |
| Odmowa dostępu do danych innej firmy | izolacja firm przeżyła odtworzenie |
| Pobranie pliku dokumentu | bajty plików wróciły, nie tylko wiersze |
| Treść i fragmenty wiedzy | wektory wróciły; bot ma z czego odpowiadać |

Nie wysyłaj z odtworzonego środowiska wiadomości, nie wołaj płatności ani modelu.

## Krok D: pomiar RPO i RTO

Czas wypisany przez polecenie obejmuje tylko jego własny proces - to nie jest RTO.
Wypełnij tabelę własnymi pomiarami:

| Pozycja | Zmierzone | Uwagi |
|---|---|---|
| Długość okna wstrzymania zapisów (krok A) | | realna przerwa dla klientów |
| Czas tworzenia kopii | | |
| Rozmiar kopii | | rośnie z bazą wiedzy klientów |
| Czas pobrania kopii z R2 | | zależy od łącza |
| Czas przygotowania środowiska (baza, migracje) | | |
| Czas samego odtworzenia | | wypisuje polecenie |
| Czas sprawdzeń z kroku C | | |
| **RTO (suma od decyzji do działającej aplikacji)** | | |
| **RPO (wiek ostatniej zweryfikowanej kopii)** | | z częstotliwości, nie z tego testu |

RPO bierze się z tego, jak często kopia powstaje, a nie z powodzenia jednej próby.
Przy kopii dziennej RPO to do 24 godzin utraconych danych; przy pełnej kopii
raz w miesiącu - do miesiąca, jeśli dzienna zawiedzie.

## Krok E: harmonogram i alarmy

To jest warunek, o który najłatwiej się potknąć, bo wszystko wygląda dobrze,
dopóki nie sprawdzisz.

1. **Kopia dzienna na Renderze.** Zadanie cron z
   [przykładowego Blueprintu](render-backups.example.yaml), komenda
   `python manage.py backup_data --to-storage`. **To jest osobno rozliczana
   usługa Rendera** - wymaga Twojej decyzji o koszcie, tak jak ustaliliśmy
   przy budżecie.
2. **Kontrola dzienna na Renderze:** `python manage.py check_backup --max-age-hours 30`,
   osobne zadanie, token do odczytu.
3. **Kontrola pełnej kopii:** `python manage.py kontrola_pelnej_kopii` - po każdym
   oknie pełnej kopii, ręcznie, albo jako trzecie zadanie cron z progiem 744 godzin.
4. **Niezależny monitor braku przebiegów** (bez kosztu): w repozytorium backendu
   dodaj sekrety `BACKUPS_STORAGE_BUCKET_NAME`, `BACKUPS_ACCESS_KEY_ID`,
   `BACKUPS_SECRET_ACCESS_KEY`, `BACKUPS_S3_ENDPOINT_URL` z tokenu R2 **tylko do
   odczytu i listowania**, a potem odkomentuj `schedule` w
   [`kontrola-kopii.yml`](../.github/workflows/kontrola-kopii.yml).
5. **Sprawdź alarm, zamiast zakładać, że działa.** Uruchom przebieg ręcznie
   z progiem `--pelna-godzin 1`: ma zejść czerwony, a powiadomienie ma trafić do
   Twojej skrzynki. Dopiero to jest dowodem. Zapisz datę tej próby.

| Alarm | Wywołany próbnie | Powiadomienie odebrane |
|---|---|---|
| Błąd zadania kopii na Renderze | | |
| Stara kopia (`check_backup`) | | |
| Brak przebiegu (GitHub Actions) | | |

## Krok F: sprzątanie

Usuń wyłącznie testową bazę `saas_restore_*` i prywatny katalog próby. Nie usuwaj
kopii, kluczy ani niczego z produkcji. Zapisz wynik odbioru w tym dokumencie:
datę, wersję kodu, zmierzone czasy i wykryte problemy.

## Wynik odbioru

Do wypełnienia po przeprowadzeniu. Dopóki ta sekcja jest pusta, F21 zostaje otwarte,
a razem z nim retencja z F20 i kasowanie plików osieroconych z F18.
