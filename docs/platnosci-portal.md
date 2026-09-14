# F11, część 2 - zmiana planu, stan zakupu i nieudana płatność

**Wersja:** 2.1.0. **Zakres:** `api/utils/stripe_portal.py` (nowy),
`api/views/stripe.py`, `api/views/stripe_webhook.py`, `accounts/tasks_konce.py`,
panel: ekran Subskrypcja i strona sukcesu płatności.

**Wdrożenie:** bez migracji i bez nowych zdarzeń webhooka. Najpierw backend,
potem panel - nowa strona sukcesu pyta o nowy endpoint. Stary panel działa
z nowym backendem.

Część 1 i wynik jej odbioru: [platnosci-spojnosc.md](platnosci-spojnosc.md).

---

## Decyzje właściciela (14.09.2026)

| Sprawa | Decyzja |
|---|---|
| Jak zmieniać plan i kartę | Portal klienta Stripe |
| Wyższy plan | Od razu, dopłata proporcjonalna za resztę okresu |
| Niższy plan | Od następnego okresu, bez zwrotów i korekt faktur |
| Nieudana płatność | Nasz e-mail do właściciela |

## Co było nie tak

| # | Sytuacja | Skutek |
|---|---|---|
| 1 | Klient z aktywną subskrypcją chce inny plan | Zablokowane w części 1 - jedyną drogą był drugi zakup, czyli druga subskrypcja |
| 2 | Płatność za odnowienie nie przeszła | Klient nie miał jak zmienić karty, a właściciel nie dostawał żadnej informacji. Czat działał do końca okresu + 3 dni i milkł bez uprzedzenia |
| 3 | Powrót ze Stripe na stronę sukcesu | Strona pytała o ogólny stan planu: firma w okresie próbnym widziała „plan aktywny", zanim cokolwiek się stało; wygasła sesja wyglądała jak spóźniony webhook |
| 4 | Webhook nie dociera (awaria, zła konfiguracja) | Klient zapłacił, a plan nie aktywował się, dopóki Stripe nie ponowił zdarzenia |
| 5 | Pracownik albo konto do podglądu | Mogło rozpocząć zakup planu dla całej firmy |
| 6 | Odmowa zakupu | Panel pokazywał `["Masz już aktywną subskrypcję..."]` |

## Jak jest teraz

1. **Zmiana planu w portalu Stripe, na tej samej subskrypcji** (punkt 1).
   Przy aktywnej subskrypcji Stripe przycisk planu w panelu to „Przejdź na Pro".
   `POST /api/billing/portal/` z `plan_type` otwiera portal od razu na ekranie
   potwierdzenia tej zmiany: Stripe pokazuje dopłatę albo datę, od której
   obowiązuje niższy plan. Po potwierdzeniu wraca do `/subskrypcja?zmiana=1`.
   Plan w bazie zmienia webhook `customer.subscription.updated` - ta sama
   synchronizacja co w części 1. Obniżka czeka w Stripe na koniec okresu
   i dopiero wtedy przychodzi jako zmiana subskrypcji.
2. **Konfiguracja portalu z kodu.** Przy pierwszym otwarciu aplikacja szuka
   w Stripe konfiguracji oznaczonej `sm_art_portal` z wersją i skrótem cen;
   jeśli jej nie ma, zakłada ją (z kluczem idempotencji) i zapamiętuje na
   godzinę. Nowa cena w zmiennych środowiskowych albo zmiana w kodzie
   (`WERSJA_KONFIGURACJI`) daje nową konfigurację. Test i produkcja mają swoje,
   nikt nie klika ich ręcznie. Ustawienia:
   - zmiana ceny: `always_invoice` (faktura na różnicę od razu), obniżka
     i skrócenie okresu na koniec okresu (`schedule_at_period_end`),
   - anulowanie z końcem opłaconego okresu,
   - karta i historia faktur włączone,
   - edycja danych klienta **wyłączona** - NIP i adres zmienia się w panelu,
     inaczej faktura rozjechałaby się z danymi firmy.
3. **„Zarządzaj subskrypcją"** (portal bez planu) dla karty, faktur
   i anulowania. Widoczne dla właściciela firmy, która ma kartotekę w Stripe.
4. **Stan konkretnego zakupu** (punkty 3 i 4).
   `GET /api/billing/checkout-session/<session_id>/` zwraca:

   | status | kiedy |
   |---|---|
   | `aktywna` | sesja opłacona, subskrypcja z tej sesji daje dostęp |
   | `w_toku` | płatność jeszcze przetwarzana albo subskrypcja jeszcze niekompletna |
   | `wygasla` | sesja wygasła bez zapłaty |
   | `nieaktywna` | subskrypcja z tego zakupu już nie działa |

   Sesja innej firmy daje 404, tak samo jak nieistniejąca. Identyfikator spoza
   wzorca `cs_test_...`/`cs_live_...` nie trafia do Stripe. Awaria Stripe daje
   503 i panel próbuje dalej. **Uzgodnienie:** gdy sesja jest opłacona, a baza
   nie zna jeszcze jej subskrypcji, endpoint pobiera subskrypcję ze Stripe
   i zapisuje stan tą samą funkcją co webhook, pod blokadą wiersza firmy.
   Spóźniony webhook zapisze później to samo.
5. **E-mail przy nieudanej płatności** (punkt 2). Jedna wiadomość przy przejściu
   subskrypcji w `past_due`: plan, data, do której działa czat, i gdzie zmienić
   kartę. Kolejne zdarzenia tej samej nieudanej płatności nie wysyłają
   następnych - przejście widzi tylko jedno z nich dzięki blokadzie wiersza.
   Po odzyskaniu płatności i kolejnej porażce wiadomość idzie znowu. Zadanie
   startuje po zatwierdzeniu zapisu i nie wysyła nic, jeśli w międzyczasie
   ponowiona płatność przeszła. Ekran Subskrypcja pokazuje to samo ostrzeżenie
   z przyciskiem „Zmień kartę".
6. **Zakup, portal i stan zakupu tylko dla właściciela** (punkt 5). Pracownik
   i podgląd widzą plan i zużycie, bez przycisków.
7. **Odmowy jako jedno zdanie** `{"detail": "..."}` (punkt 6). Panel dodatkowo
   składa listę z DRF w zdanie, gdyby podobny błąd przyszedł z innego miejsca.
8. **Bez fałszywego „kończy się za 3 dni" w dniu odnowienia.** Od części 1 koniec
   subskrypcji Stripe to koniec okresu + 3 dni. Przegląd końców chodzi o 8:15,
   Stripe odnawia o godzinie zakupu, więc firma, która kupiła plan po 8:15,
   dostawałaby to ostrzeżenie co miesiąc. Subskrypcja Stripe w stanie `active`
   lub `trialing` odnawia się sama i nie dostaje alertów końca; `past_due`
   dostaje je nadal (`Subscription.prog_konca_do_powiadomienia`).

## Świadome ograniczenia

- **Plany roczne nie są w portalu** - w Stripe nie ma jeszcze cen rocznych.
  Po ich dodaniu wystarczy nowa wersja konfiguracji.
- **Panel nie pokazuje zaplanowanej obniżki ani anulowania z końcem okresu.**
  Do końca okresu subskrypcja w Stripe jest `active`, więc panel pokazuje
  bieżący plan; szczegóły są w portalu.
- **Stare konfiguracje portalu zostają w Stripe** po zmianie cen albo wersji.
  Nie są używane i niczego nie zmieniają.
- **Pierwsza konfiguracja założona przez API staje się domyślną konfiguracją
  konta Stripe** i Stripe nie pozwala jej wyłączyć. W trybie testowym stała
  się nią próbna konfiguracja z 14.09.2026 - nieużywana przez aplikację.
- **Przypomnienie Stripe o nieudanej płatności nie jest włączone.** Właściciel
  dostaje nasz e-mail, a potem istniejące alerty końca dostępu (3 dni przed
  i po wygaśnięciu). Ostrzeżenie „za 3 dni" przychodzi zwykle tego samego dnia
  co e-mail o nieudanej płatności - obie wiadomości są prawdziwe.
- **Anulowanie z końcem okresu nie dostaje alertu końca.** Do końca okresu
  subskrypcja jest `active`; o dacie informuje portal przy anulowaniu.

## Weryfikacja

`api/tests/test_platnosci_portal.py`, 38 przypadków, oraz testy panelu
(`test/subskrypcja.test.tsx`, przebudowany `test/platnosc.test.tsx`,
`test/api.test.ts`) i pomiar celów w `e2e/responsywnosc.spec.ts` z nową atrapą
ekranu Subskrypcja w stanie nieudanej płatności.

**Odtworzenie błędu:** na kodzie sprzed zmiany czerwienieje 31 z 38 testów
backendu. Z siedmiu zielonych trzy sprawdzają odmowę dla cudzej, nieistniejącej
i źle zapisanej sesji - przechodzą tylko dlatego, że trasy nie było (404).
Cztery to straże: właściciel kupuje plan, nowa cena daje nowe oznaczenie
konfiguracji, udane odnowienie nie wysyła wiadomości, brak adresu nie przerywa
webhooka.

**Weryfikacja mutacyjna** (14.09.2026): 22 z 22 uszkodzeń czerwieni co najmniej
jeden test - zakup, portal i stan zakupu dla każdego zalogowanego, błąd jako
lista, dopłata dopiero przy odnowieniu, obniżka od razu, dane do faktury
edytowalne w portalu, bez pamiętania i bez odnajdywania konfiguracji, bez
sprawdzenia firmy sesji, bez uzgodnienia przed webhookiem, nieopłacona sesja
jak opłacona, bez wzorca identyfikatora, awaria Stripe jako 404, obecny plan
i subskrypcja z kilkoma pozycjami przepuszczone, zmiana planu bez aktywnej
subskrypcji, wiadomość przy każdym zdarzeniu `past_due` i przed zapisem stanu,
zadanie bez sprawdzenia bieżącego stanu, panel bez informacji o subskrypcji
Stripe i o roli.

Alert końca: dwa nowe testy w `accounts/tests/test_konce_subskrypcji.py`;
usunięcie warunku dla subskrypcji Stripe czerwieni test aktywnej subskrypcji
w dniu odnowienia.

Pomiar celów wykrył przy okazji przycisk „Usuń" przy witrynie o wysokości
16 px (wcześniej atrapa nie miała witryn). Poprawiony w tym samym PR panelu.

## Odbiór - wyłącznie w trybie testowym Stripe

Lokalnie, jak w części 1: klucz `sk_test`, `stripe listen` przekazujący
zdarzenia do lokalnego backendu, karta `4242 4242 4242 4242`.

1. **Zakup z okresu próbnego:** Checkout, powrót na stronę sukcesu - „Plan Grow
   jest już aktywny". W odpowiedzi endpointu stanu zakupu `aktywna`.
2. **Spóźniony webhook:** zatrzymany `stripe listen`, zakup, strona sukcesu
   i tak potwierdza plan (uzgodnienie), po wznowieniu zdarzenia dają `200`
   bez zmiany stanu.
3. **Podwyższenie:** „Przejdź na Pro" → portal pokazuje dopłatę → potwierdzenie.
   W panelu Pro, w Stripe ta sama subskrypcja i faktura na różnicę.
4. **Obniżenie:** „Przejdź na Start" → portal pokazuje datę zmiany. W panelu
   nadal Pro; w Stripe harmonogram na koniec okresu. Test clock przesunięty za
   koniec okresu → Start w panelu.
5. **Zarządzaj subskrypcją:** karta i faktury dostępne, danych do faktury nie da
   się zmienić.
6. **Nieudana płatność** (test clock, karta odrzucająca): jeden e-mail z datą
   końca dostępu, na ekranie Subskrypcja ostrzeżenie i „Zmień kartę".
7. **Uprawnienia:** pracownik nie widzi przycisków, `POST` do checkout i portalu
   daje 403.
8. **Cudza albo zmyślona sesja** w adresie strony sukcesu: „Nie znaleźliśmy tej
   płatności".
