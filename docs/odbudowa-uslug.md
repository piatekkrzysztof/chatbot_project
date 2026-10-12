# Odbudowa usług po awarii - instrukcja i zmierzone RTO

**Pomiar 12.10.2026, wersja 2.32.0.** Uzupełnia [odbiór F21](odbior-f21.md#krok-d-pomiar-rpo-i-rto),
który zmierzył odzyskanie danych (~10 min), ale nie powrót działającej usługi.
Zgodnie z decyzją właściciela z 11.10.2026 próba odbyła się lokalnie, bez
nowych płatnych usług na Renderze.

## Najważniejsze ryzyko - sekrety tylko w Renderze

**Stan na 12.10.2026: wartości zmiennych środowiskowych nie są zapisane nigdzie
poza panelem Rendera.** `render.yaml` deklaruje 34 zmienne, z czego 28 to
wartości wpisywane ręcznie (`sync: false`). Przy utracie konta lub usług
na Renderze nie da się ich odtworzyć, a dwie z nich są warunkiem odtworzenia
kopii w ogóle:

- `BACKUP_ENCRYPTION_KEY` - bez niego kopia `.saas` jest nieczytelna;
- `DJANGO_SECRET_KEY` - odtwarzanie sprawdza zgodność klucza z kopią
  (MFA, sesje, podpisy); inny klucz to odmowa.

**Do zrobienia przez właściciela:** przepisać wszystkie 28 wartości do
menedżera haseł (osobny wpis na usługę: backend, worker, strona), a przy
każdej zmianie w Renderze aktualizować wpis. Wartości nie trafiają do
repozytorium ani do dokumentacji.

## Scenariusze i czas powrotu

| Scenariusz | Droga | RTO |
|---|---|---|
| **1. Zły wdrożony kod** (baza i usługi zdrowe) | Render → usługa → Rollback do poprzedniego wdrożenia (web i worker) | **~2 min** - zmierzone: wdrożenie web 2 min, worker 1 min (12.10.2026) |
| **2. Utrata lub uszkodzenie bazy** (Render działa) | a) PITR Rendera do chwili przed awarią - albo b) nasza kopia `.saas` (niżej) | a) wg Rendera, niezmierzone; b) **~25-35 min** |
| **3. Utrata usług lub konta Rendera** | Nowe usługi z `render.yaml` (Blueprint), sekrety z menedżera haseł, dane jak w 2b, przepięcie domeny | **~1,5-2 h** przy sekretach pod ręką; **niewykonalne bez nich** |

Pliki klientów (dokumenty, logo, awatary) są w **R2**, nie na Renderze -
w scenariuszach 1-3 zostają nietknięte. Odtworzenie plików z kopii jest
potrzebne dopiero przy utracie samego R2 (patrz niżej).

## Scenariusz 2b - z kopii `.saas` do nowej bazy Rendera

| Krok | Czas | Skąd liczba |
|---|---|---|
| Pobranie najnowszej kopii z R2 | < 1 min | F21, 17.09 |
| Lokalnie: pusta baza PostgreSQL 16 + pgvector (kontener), migracje | 8 s - 3 min | 12.10: 8 s na gotowym serwerze; F21: ~3 min z uruchomieniem kontenera |
| `restore_full_backup` do lokalnej `saas_restore_*` | **7 s** (polecenie 2,8 s) | 12.10, skala produkcji: 3 firmy, 763 fragmenty, 210 rozmów, 15 plików |
| Sprawdzenie liczby rekordów | ~2 min | F21 krok C |
| Nowa baza Postgres na Renderze (ten sam plan i region) | ~5-10 min | **niezmierzone** - tworzenie instancji przez Render |
| `pg_dump -Fc` z lokalnej bazy i `pg_restore --no-owner --no-acl` do nowej (zewnętrzny adres bazy Rendera, klient pg 16 lub nowszy) | **2 s** lokalnie (zrzut 2 MB) + przesył | 12.10 |
| `DATABASE_URL` web i workera → nowa baza; restart | 1-2 min | wdrożenia 12.10 |
| `/health/` → `stan=ok` | **11 s** po przełączeniu (do 80 s, gdy Beat startuje od zera) | 12.10 |
| Kontrola: logowanie, historia rozmów, pobranie pliku | ~2 min | 12.10: wszystko 200 |

**Polecenia** (lokalnie, w izolacji - zasady z
[pełnej kopii](pelna-kopia-i-odtworzenie.md#próba-odtworzenia--nowa-lokalna-baza)):

```sh
python manage.py restore_full_backup /prywatny/kopia.saas --output /prywatny/odtworzenie
pg_dump -h 127.0.0.1 -U postgres -Fc --no-owner --no-acl -f /prywatny/zrzut.dump saas_restore_NAZWA
pg_restore --no-owner --no-acl -d "ZEWNETRZNY_ADRES_NOWEJ_BAZY_RENDERA" /prywatny/zrzut.dump
```

Nowa baza na Renderze musi mieć rozszerzenie `vector` (Render je udostępnia;
`pg_restore` tworzy je z zrzutu). Zrzut przechowywać jak kopię - zawiera dane
klientów; usunąć po udanym odtworzeniu.

**RPO** wynika z częstotliwości kopii: pełna kopia ręcznie raz w miesiącu
(decyzja właściciela) - do miesiąca utraconych danych, chyba że jest
świeższa kopia dzienna albo PITR Rendera.

## Scenariusz 3 - dodatkowo

1. Render → **New → Blueprint** z repozytorium: tworzy web, worker i Redis
   według `render.yaml` (baza: osobno, jak w 2b).
2. Sekrety z menedżera haseł do każdej usługi; `PYTHON_VERSION` = `3.11.17`.
3. Pierwsze budowanie bez pamięci podręcznej - dłuższe niż 1-2 min z wdrożeń
   codziennych (niezmierzone).
4. Domeny: `api.agencjasm-art.pl` (CNAME) na nowy adres `*.onrender.com`,
   dodanie domeny w usłudze i certyfikat Rendera - od kilku minut do godziny
   zależnie od TTL rekordu.
5. Webhook Stripe: nowy adres tylko gdy zmienia się domena; przy tej samej
   `api.agencjasm-art.pl` - bez zmian. Ten sam `STRIPE_WEBHOOK_SECRET`.
6. Panel (Vercel) i strona marketingowa - bez zmian, o ile domena API została.

## Utrata R2

Pliki są w kopii `.saas` (bajty każdego pliku z bazy). `restore_full_backup`
odtwarza je do katalogu `--output` (`private_documents/...`); stamtąd wgrać
do nowego koszyka R2 z zachowaniem nazw (np. `rclone copy`). Kopie
przechowywane w tym samym R2 przepadają razem z nim - kopia lokalna u
właściciela jest wtedy jedyną drogą.

## Próba z 12.10.2026 - przebieg

Kod ze świeżego klona `main` (6011af0, 2.32.0). Źródło: osobna baza
z danymi syntetycznymi w skali produkcji, kopia `backup_full` (11 MB
zaszyfrowanej, 15 plików) z kluczem próbnym. Odtworzenie do pustej
`saas_restore_rto` po migracjach, pliki na miejsce, Redis, web, worker
i Beat → `stan=ok` po 83 s (czekanie na pierwszą próbę Beat). Potem droga 2b:
`pg_dump`/`pg_restore` do nowej pustej bazy i przełączenie aplikacji →
`stan=ok` po 11 s. Kontrola na obu bazach: logowanie właściciela z kopii,
pulpit, historia rozmów, lista dokumentów i pobranie pliku - wszystko 200,
liczby rekordów zgodne ze źródłem 1:1.

**Czego próba nie mierzy:** tworzenia usług i bazy na Renderze, zimnego
budowania na Renderze, przepięcia DNS i certyfikatu. Instalacja zależności
lokalnie nie była miarodajna (sieć tej sesji przechwytuje TLS) - czas budowania
pochodzi z wdrożeń Rendera. Po próbie bazy, procesy i pliki z kluczem próbnym
usunięte.
