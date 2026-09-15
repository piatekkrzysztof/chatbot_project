# F16, część 3 - czasy odpowiedzi, SLO i koszt uwierzytelnienia

**Wersja:** 2.4.1. **Zakres:** `chatbot_project/pomiar_czasu.py` (nowy),
`api/session_tokens.py`, `chatbot_project/settings/base.py`, publiczne widoki
widgetu (`api/views/widget.py`, `contact.py`, `feedback.py`), `api/views/stripe.py`.

**Wdrożenie:** bez migracji, bez zmian w panelu. Opcjonalnie zmienna
`WOLNE_ZADANIE_MS` (domyślnie 1000, 0 wyłącza pomiar).

---

## Co było nie tak

| # | Sytuacja | Skutek |
|---|---|---|
| 1 | Żądanie panelu z JWT | `TenantMiddleware` i DRF osobno uwierzytelniały żądanie: dwa odczyty użytkownika, sesji logowania i firmy. `/api/accounts/me/` - 7 zapytań, 3 powtórzone (pomiar 15.09.2026) |
| 2 | Każdy ekran panelu | Obowiązywał także limit czatu firmy. Bez aktywnego planu 30 żądań na minutę na cały panel - klient z wygasłym planem dostawał 429, a ruch widgetu odwiedzających zjadał limit panelu |
| 3 | Wolne żądanie | Jedynym śladem był Sentry z próbkowaniem 10% - dziewięć na dziesięć wolnych żądań nie zostawiało nic |

## Jak jest teraz

1. **Jedno uwierzytelnienie na żądanie.** `SessionJWTAuthentication` zapamiętuje
   wynik na żądaniu Django razem z nagłówkiem `Authorization`, z którego powstał.
   DRF dostaje ten sam wynik, zamiast sprawdzać token od nowa. Inny nagłówek na
   tym samym obiekcie żądania jest sprawdzany od nowa, a błąd uwierzytelnienia nie
   jest zapamiętywany. Sesja i użytkownik: 1 odczyt zamiast 2; firma też raz.
2. **Limit panelu oddzielony od limitu czatu.** Domyślnie obowiązuje tylko
   `SubscriptionRateThrottle` (10x stawka planu). Widoki ruchu odwiedzających
   ustawiają limit czatu jawnie: czat i strumień (jak dotąd), a teraz także
   ustawienia widgetu, publiczne FAQ, kontakt i ocena odpowiedzi. Test przegląda
   wszystkie trasy `widget/` i `widget-settings/` - nowy publiczny widok bez
   limitu czatu czerwieni CI. Osobne ustawienie limitu na ekranach płatności
   (2.2.0) nie jest już potrzebne.
3. **Wolne żądania w logu.** Każde żądanie API dłuższe niż `WOLNE_ZADANIE_MS`
   zostawia jedną linię:

   ```
   Wolne żądanie: GET api/documents/(?P<pk>[^/.]+)/$ -> 404 w 2500 ms, zapytań SQL: 3
   ```

   Trasa jako wzorzec - bez identyfikatorów, parametrów zapytania i treści
   żądania. Liczba zapytań SQL od razu mówi, czy szukać w bazie, czy w kodzie.

## SLO - cele (propozycja do akceptacji właściciela)

Na obecnych zasobach (jedna instancja web na Renderze, PostgreSQL z pgvector),
bez nowych płatnych narzędzi.

| Obszar | Cel | Skąd liczba |
|---|---|---|
| Ekrany i listy panelu | p95 poniżej 800 ms, żadne żądanie powyżej 3 s | linie „Wolne żądanie" w logu web, Sentry Performance |
| Widget: ustawienia, FAQ, kontakt | p95 poniżej 500 ms | jw. |
| Widget: pierwszy fragment odpowiedzi czatu | p95 poniżej 3 s | Sentry (transakcja strumienia); czas modelu OpenAI to większość |
| Webhook Stripe | p95 poniżej 2 s | linie w logu, lista zdarzeń w panelu Stripe |
| Błędy 5xx | poniżej 0,5% żądań w tygodniu | Sentry |
| Dostępność `/health/` | 99,5% w miesiącu | monitor Rendera |

**Jak sprawdzać (raz w tygodniu, 10 minut):**

1. Render → usługa web → Logs → wyszukaj `Wolne żądanie`. Kilka linii dziennie
   na tych samych trasach to kandydat do pomiaru; dziesiątki - problem.
2. Sentry → Performance: p95 dla tras panelu i widgetu z ostatnich 7 dni.
3. Nowa trasa z dużą liczbą zapytań SQL w linii - sprawdzić, czy nie wróciło
   zapytanie w pętli (test `test_wydajnosc_list.py` pilnuje list panelu).

## Świadome ograniczenia

- **Cele nie są jeszcze zmierzone na produkcji.** Pierwszy tydzień po wdrożeniu
  to pomiar wyjściowy; cele mogą wymagać korekty po jego wyniku.
- **Czas do zwrócenia odpowiedzi.** Przy odpowiedziach strumieniowych (czat
  widgetu, eksport CSV) linia nie obejmuje wysyłania treści.
- **Brak testu obciążeniowego.** Liczba jednoczesnych rozmów, którą utrzyma
  instancja, należy do odbioru komercyjnego (etap 8).
- Limit czatu nadal liczy się per firma dla całego ruchu widgetu (ustawienia,
  FAQ i rozmowy razem) - jak przed zmianą.

## Weryfikacja

`api/tests/test_sesja_limity_czasy.py`: 12 testów.

**Odtworzenie:** na kodzie sprzed zmiany czerwienieje 7 z 12 - podwójny odczyt
sesji i użytkownika na trzech ekranach, 429 dla firmy bez aktywnego planu, limit
czatu wśród domyślnych, brak linii wolnego żądania i liczby zapytań. Pięć
zielonych to straże: odwołana sesja nadal odrzucona, inny nagłówek sprawdzany od
nowa, widget nadal dostaje 429, szybkie żądanie bez linii oraz przegląd tras
widgetu - ten ostatni przechodzi na starym kodzie, bo limit czatu był wtedy
domyślny; chroni nową konfigurację.

**Mutacje** (15.09.2026): 10 z 10 uszkodzeń czerwieni co najmniej jeden test -
drugie uwierzytelnienie mimo zapamiętania, zapamiętanie bez porównania nagłówka,
limit czatu z powrotem domyślny, publiczne FAQ, kontakt i ocena bez limitu czatu,
niepodpięty middleware, próg dziesięć razy wyższy, pełny adres zamiast wzorca
trasy, niezliczone zapytania.

Testy powiązane (limity, sesje, płatności, kontakt, oceny, widget, granice
dostępu, schemat): 342 passed.
