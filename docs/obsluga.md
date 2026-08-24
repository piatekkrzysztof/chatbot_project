# Obsługa — od objawu do komendy

Ściąga operacyjna. Bez teorii: co odpalić, kiedy i czego się spodziewać.
Wszystkie komendy uruchamiasz w powłoce usługi **chatbot-backend** na Renderze
(zakładka Shell, katalog `~/project/src`) albo lokalnie z katalogu projektu.

Rzeczy, które **wykonują się same** i nie wymagają Twojej uwagi, są opisane
na końcu — warto wiedzieć, że istnieją, zanim zaczniesz szukać przyczyny
w niewłaściwym miejscu.

---

## Nowy klient

```bash
python manage.py bootstrap_tenant \
  --company "Nazwa Firmy" \
  --email "wlasciciel@firma.pl" \
  --password "haslo-ktore-przekazesz" \
  --plan grow \
  --message-limit 8000
```

Zakłada firmę, konto właściciela i subskrypcję. Wypisuje **klucz widgetu**
i gotowy kod osadzenia z prawdziwym adresem panelu — do wklejenia na stronę
klienta przed zamykającym `</body>`.

Dalej klient (albo Ty na jego koncie):

1. **Baza wiedzy → Strony WWW** — wkleja adres swojej witryny. Pobieranie
   startuje od razu; przy dwudziestu podstronach trwa około pół minuty.
   Lista dokumentów odświeży się po przeładowaniu strony.
2. **Stan** — karta „Wiedza, którą zna bot" powinna świecić na zielono.
   Jeśli pokazuje ostrzeżenie, zobacz [Bot zna za mało](#bot-zna-za-mało).
3. **Test bota** — pięć pytań, które zadałby prawdziwy klient. To jedyny
   sposób, żeby sprawdzić jakość, zanim widget trafi na żywą stronę.
   Ta rozmowa nie zużywa limitu wiadomości i nie wchodzi do statystyk.
4. **Baza wiedzy** — odznaczenie w kolumnie „W wyszukiwaniu" tego, co nie
   zawiera faktów: sekcji kontaktowej, polityki prywatności, strony głównej
   złożonej z samych haseł.
5. **Ustawienia konta** — sprawdzenie adresu, na który mają iść powiadomienia.

Zmierzone przy próbie generalnej: od założenia konta do działającego bota
z dwudziestoma podstronami — **kilka minut**, z czego większość to czekanie
na pobranie strony.

---

## „Nie dostaję maili"

Trzy różne przyczyny, trzy różne miejsca. Zaczynaj od pierwszej.

```bash
python manage.py sprawdz_poczte
```

Pokazuje konfigurację, kształt wartości i **realne połączenie** z serwerem
poczty. Dopisz `--wyslij adres@example.com`, żeby wysłać próbny list.

To sprawdza usługę **web**. Powiadomienia wysyła jednak **worker**, który ma
własny komplet zmiennych — a te już raz się rozjechały. Konfigurację workera
obejrzysz tylko stamtąd:

```bash
python manage.py shell -c "
from chat.tasks import sprawdz_poczte_task
[print(w) for w in sprawdz_poczte_task.delay().get(timeout=30)]
"
```

Jeśli poczta działa, a klient dalej nie dostaje listów — sprawdź adres:

```bash
python manage.py shell -c "
from accounts.models import Tenant
[print(t.id, t.name, '->', t.owner_email) for t in Tenant.objects.all()]
"
```

Adres zmienia się w panelu: **Ustawienia konta**. Zapytania, których nie udało
się wysłać, mają zapisany powód — widać go na stronie **Zapytania** przy
konkretnej pozycji.

---

## Bot zna za mało

Objaw: bot odmawia przy pytaniach, na które strona klienta odpowiada.

Najpierw zobacz, co w ogóle wciągnął:

```bash
python manage.py shell -c "
from documents.models import Document, DocumentChunk
for d in Document.objects.filter(tenant_id=NUMER).order_by('name'):
    ile = DocumentChunk.objects.filter(document=d).count()
    flaga = ' ' if d.uzywaj_w_wyszukiwaniu else '×'
    print(f'{flaga} {len(d.content or \"\"):>6} zn. {ile:>3} fragm.  {d.name[-52:]}')
"
```

Trzy typowe obrazy:

- **Zero fragmentów przy niezerowej treści** — wektory się nie policzyły.
  Zwykle znaczy to, że worker nie działał w chwili pobierania. Napraw wektory
  komendą `przelicz_fragmenty --wykonaj` (niżej).
- **Podstrona z kilkuset znakami przy innych po kilka tysięcy** — ze strony
  wyciągnęliśmy ułamek treści. Porównaj warianty ekstrakcji:
  `python manage.py zmierz_pobieranie --firma NUMER`
- **Wszystko wygląda dobrze, a bot i tak odmawia** — to nie baza wiedzy,
  tylko próg wyszukiwania. Zobacz [Próg odległości](#próg-odległości).

Karta „Wiedza, którą zna bot" na stronie **Stan** pokazuje pierwsze dwa
przypadki sama, z nazwami dokumentów.

---

## Po zmianie w sposobie dzielenia treści

Zmiana kodu **nie rusza** fragmentów, które już leżą w bazie. Trzeba je
przeliczyć — najpierw na sucho, bo to płatne wywołania API:

```bash
python manage.py przelicz_fragmenty --firma NUMER
python manage.py przelicz_fragmenty --firma NUMER --wykonaj
```

Bez `--firma` bierze wszystkie firmy. Bezpieczne do powtórzenia: przeliczanie
kasuje stare fragmenty przed zapisaniem nowych, więc nie dubluje.

---

## Próg odległości

`RAG_MAX_DISTANCE` decyduje, jak daleko od pytania może leżeć fragment, żeby
trafił do odpowiedzi. Za wysoko — bot dostaje śmieci i musi się z nimi mocować.
Za nisko — odmawia mimo posiadanej wiedzy.

Wartości nie da się zgadnąć: zależy od dokumentów konkretnego klienta.

```bash
python manage.py zmierz_prog_rag --firma NUMER \
  --pytanie "coś, na co firma odpowiada" \
  --pytanie "coś spoza jej oferty"
```

Ostatni wiersz podsumowania podaje próg rozdzielający grupy. Ustawiasz go
w Render → **chatbot-backend** → Environment → `RAG_MAX_DISTANCE`. Tylko tam:
wyszukiwanie działa w procesie web, worker o nic nie pyta.

Gdy komenda napisze „grupy się nakładają", przeczytaj listę spornych wpisów.
Zwykle są to pytania sprzed poprawki rozpoznawania odmowy, oznaczone jako
odpowiedziane, choć bot na nie nie odpowiedział — wtedy pomijasz je i liczysz
granicę z reszty.

Przemierz po każdej większej zmianie w bazie wiedzy. Fragmenty się zmieniają,
próg razem z nimi.

---

## „Coś nie działa, a nie wiem co"

Panel → **Stan**. Pięć kart:

| | co pokazuje | co znaczy czerwone |
|---|---|---|
| 01 | kolejka zadań | worker nie żyje — zadania cykliczne stoją |
| 02 | pobieranie stron | treści się nie odświeżają |
| 03 | usuwanie starych rozmów | RODO: dane nie są kasowane |
| 04 | wiedza bota | dokumenty bez wektorów albo niepełne podstrony |
| 05 | powiadomienia | poczta nie działa albo brak adresu |

Karta 01 to jedyna, przy której klient nic nie zrobi — to sprawa dla Ciebie.
Reszta ma konkretne działanie po stronie klienta.

Szczegóły kolejki, gdy karta 01 świeci na czerwono:

```bash
curl -H "X-API-Key: KLUCZ" https://TWOJ-BACKEND/api/diagnostyka/zadania/
```

---

## Rzeczy, które dzieją się same

Warto je znać, zanim zaczniesz szukać przyczyny w niewłaściwym miejscu.

| kiedy | co |
|---|---|
| co 12 godzin | pobieranie stron — ale każdą firmę tylko tak często, jak przewiduje jej plan (Start ręcznie, Grow co 7 dni, Pro codziennie) |
| codziennie 3:30 | kasowanie rozmów po okresie retencji ustawionym przez klienta |
| poniedziałki 8:00 | raport luk w wiedzy — tylko do firm, które mają jakieś luki i włączony raport |
| przy każdym wdrożeniu | migracje bazy (`build.sh`, usługa web) |

Wszystko powyższe wymaga **działającego workera**. Bez niego zadania z żądań
HTTP wykonują się na miejscu (wolniej, ale działają), a zadania z harmonogramu
po prostu nie chodzą — i nic tego nie zgłasza poza kartą 01.

---

## Zmienne środowiskowe, które muszą być na obu usługach

`chatbot-backend` **i** `celery-worker` mają osobne komplety zmiennych i nic
ich ze sobą nie porównuje. Rozjechały się już dwa razy, za każdym razem
zatrzymując pocztę:

```
EMAIL_HOST  EMAIL_PORT  EMAIL_HOST_USER  EMAIL_HOST_PASSWORD  DEFAULT_FROM_EMAIL
DATABASE_URL  DJANGO_SECRET_KEY  OPENAI_API_KEY  REDIS_URL  FRONTEND_URL
```

Tylko na **web**: `RAG_MAX_DISTANCE`, `DJANGO_ALLOWED_HOSTS`,
`DJANGO_CORS_ALLOWED_ORIGINS`, `STRIPE_*`.

Pełna lista z komentarzami jest w `render.yaml` — plik niczego nie tworzy sam
z siebie, ale mówi, co ma istnieć i gdzie.
