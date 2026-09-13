# F11, część 1 - spójność płatności ze Stripe

**Zakres:** `api/views/stripe_webhook.py` (przebudowany), `api/views/stripe.py`
(checkout), `accounts/models.py` i migracja `0038_subscription_stripe`.

**Migracja:** dwa pola na `Subscription` z wartością domyślną -
`stripe_subscription_id` i `stripe_status`. Bez przenoszenia danych: na dzień
zmiany żadna firma nie ma płatnej subskrypcji w Stripe (potwierdzone przez
właściciela 13.09.2026).

**Wdrożenie:** migracja, potem web i worker z tym samym commitem.

---

## Co było zepsute

Webhook wykonywał każde zdarzenie jak polecenie: „zapłacono - aktywuj na 31 dni",
„nieudana płatność - zawieś", „usunięto - zawieś". Stripe nie gwarantuje
kolejności zdarzeń, ponawia je do trzech dni i czasem dostarcza podwójnie.

| # | Sytuacja | Skutek |
|---|---|---|
| 1 | Stripe ponawia stary `checkout.session.completed` po anulowaniu | Dostęp wraca na 31 dni bez płatności |
| 2 | `invoice.payment_failed` z wcześniejszej próby dociera po udanej płatności | Opłacony klient odcięty |
| 3 | Pierwsza nieudana próba odnowienia | Czat wyłączony od razu, choć Stripe ponawia płatność kilka dni |
| 4 | `customer.subscription.deleted` starej subskrypcji po zakupie nowej | Nowa, opłacona subskrypcja zawieszona |
| 5 | Sesja Checkout zakończona bez zapłaty | Plan aktywowany |
| 6 | Plan roczny | Okres „dziś + 31 dni", potem odcięcie mimo opłaconego roku |
| 7 | Zmiana planu po stronie Stripe | Nieobsługiwana - limit dawnego planu |
| 8 | Przejściowa awaria Stripe przy fakturze | 200 i zdarzenie przepada, Stripe nie ponawia |
| 9 | Klient z aktywną subskrypcją kupuje inny plan w panelu | **Druga subskrypcja w Stripe - dwa obciążenia co miesiąc** |
| 10 | Podwójne kliknięcie „Kup" | Dwie niezależne sesje Checkout, każdą da się opłacić |

## Jak jest teraz

1. **Zdarzenie wskazuje subskrypcję, stan przychodzi ze Stripe.** Webhook ustala,
   której subskrypcji dotyczy zdarzenie (sesja, faktura w każdym znanym
   kształcie, sama subskrypcja), pobiera jej bieżący stan
   `stripe.Subscription.retrieve` i przepisuje go do bazy. Powtórka, duplikat
   i zła kolejność dają ten sam wynik - punkty 1, 2 i 5.
2. **Dostęp według statusu Stripe:**

   | status | dostęp | koniec |
   |---|---|---|
   | `active`, `trialing` | tak | koniec okresu ze Stripe + 3 dni |
   | `past_due` | tak | koniec OSTATNIEGO OPŁACONEGO okresu + 3 dni |
   | `canceled`, `unpaid`, `incomplete_expired`, `paused` | nie | - |
   | `incomplete` | bez zmian | pierwsza płatność jeszcze nie przeszła |

   `past_due` liczy od początku bieżącego okresu, bo Stripe przesuwa okres na
   nowy także wtedy, gdy płatność za niego nie przeszła. Trzy dni zapasu to
   decyzja właściciela z 13.09.2026: dostęp do końca opłaconego okresu, nie
   odcięcie przy pierwszej nieudanej próbie - punkt 3.
3. **Identyfikator subskrypcji Stripe przy firmie.** Zdarzenie o subskrypcji,
   która nie jest subskrypcją firmy, nie zmienia jej dostępu - punkt 4.
4. **Okres i plan ze Stripe.** Okres z `current_period_*`, plan z identyfikatora
   ceny (`STRIPE_PRICE_IDS` i `STRIPE_PRICE_IDS_ROCZNE`), metadane tylko
   w ostateczności - punkty 6 i 7.
5. **Błąd przejściowy Stripe to 500**, więc Stripe ponowi zdarzenie. Subskrypcja,
   której w Stripe nie ma (np. inny tryb), to 200 bez zmian - punkt 8.
6. **Pod blokadą wiersza firmy.** Zakup wysyła zwykle dwa zdarzenia w tej samej
   sekundzie; nie zakładają dwóch wierszy ani nie nadpisują się w połowie.
7. **Checkout odrzuca drugi zakup** przy aktywnej subskrypcji Stripe z czytelnym
   komunikatem - punkt 9. Zmiana planu na tej samej subskrypcji to część 2.
8. **Klucz idempotencji sesji Checkout** (firma, plan, cena, klient, okno
   10 minut): ponowne wejście zwraca tę samą sesję - punkt 10.

## Świadome ograniczenia

- **Zmiana planu z panelu jest zablokowana** do części 2. Klient z aktywną
  subskrypcją dostaje komunikat, żeby napisać - zamiast podwójnego obciążenia.
- **Dwie aktywne subskrypcje utworzone poza panelem** (np. ręcznie w Stripe)
  nie przełączają się tam i z powrotem: zostaje pierwsza, a log ma błąd do
  wyjaśnienia ręcznie.
- **Strona sukcesu w panelu nadal sprawdza tylko ogólny stan planu**, nie
  konkretną sesję - część 2 (F22).
- **Nieudana płatność nie wysyła jeszcze powiadomienia** właścicielowi firmy.

## Co trzeba ustawić w Stripe

W panelu Stripe, w punkcie końcowym webhooka `/api/billing/webhook/`, muszą być
włączone zdarzenia:

- `checkout.session.completed`
- `invoice.payment_succeeded`
- `invoice.payment_failed`
- `customer.subscription.updated` - **nowe, wcześniej nieobsługiwane**
- `customer.subscription.deleted`

## Weryfikacja

Nowy plik `api/tests/test_platnosci_spojnosc.py`, 17 przypadków.

**Odtworzenie błędu:** na kodzie sprzed zmiany (bez migracji) czerwienieje 14
z 17. Dwanaście odtwarza błąd na asercji: okres, plan roczny, sesja bez zapłaty,
powtórka po anulowaniu, spóźniona nieudana płatność, odcięcie przy pierwszej
nieudanej próbie, brak odcięcia przy unpaid, stara subskrypcja, zmiana planu,
200 zamiast 500, nieistniejąca subskrypcja, brak klucza idempotencji. Dwa
(blokada drugiego zakupu, anulowana subskrypcja nie blokuje) padają tylko przez
brak nowego pola - sam brak blokady potwierdza lektura starego checkoutu. Trzy
przechodzą także na starym kodzie i to są straże: duplikat zdarzenia, zakup
z okresu próbnego, dwa zdarzenia zakupu naraz.

**Weryfikacja mutacyjna** (13.09.2026): każde z jedenastu uszkodzeń czerwieni
co najmniej jeden test - `past_due` do końca nowego okresu, bez bufora, `past_due`
bez dostępu, dostęp przy `incomplete`, każda subskrypcja uznana za subskrypcję
firmy, plan tylko z metadanych, awaria Stripe jako 200, nieistniejąca subskrypcja
jako ponowienie, bez blokady wiersza firmy, bez blokady drugiego zakupu, bez
klucza idempotencji.

Zmienione oczekiwania istniejących testów: `TestAktywacjaPoPlatnosci`
i `TestWebhook` w `test_billing.py` oraz `TestZnajdowaniaFirmy`/`TestPelnejSciezki`
w `test_webhook_faktury.py` sprawdzają teraz synchronizację stanu ze Stripe.
Test „nieudana płatność zawiesza konto" zastąpiły dwa: pierwsza nieudana próba
zostawia opłacony okres, a status `unpaid` odcina dostęp.

## Odbiór - wyłącznie w trybie testowym Stripe

Bez prawdziwych obciążeń. Środowisko z kluczami testowymi (`sk_test_...`)
i cenami testowymi, webhook z sekretem trybu testowego.

1. Zakup planu kartą `4242 4242 4242 4242`: w panelu plan aktywny, w bazie
   `stripe_subscription_id` i `stripe_status = active`, koniec okresu zgodny
   z okresem w Stripe + 3 dni.
2. Drugi zakup innego planu w panelu: komunikat o aktywnej subskrypcji, w Stripe
   nie powstaje druga subskrypcja.
3. Anulowanie subskrypcji w panelu Stripe: po zdarzeniu dostęp wygasa.
   Ponowne wysłanie starego zdarzenia zakupu z panelu Stripe („Resend") nie
   przywraca dostępu.
4. Nieudane odnowienie przez test clock i kartę odrzucającą płatności: status
   `past_due`, czat działa do końca opłaconego okresu + 3 dni.
