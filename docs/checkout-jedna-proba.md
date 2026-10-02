# Jedna próba zakupu - A01

30.09.2026, 2.19.1. Naprawa po ponownym audycie. Nie oznacza odbioru pozostałych
ustaleń A02-A05 ani potwierdzenia wdrożenia produkcyjnego.

## Problem i zachowanie po poprawce

Klucz Checkout zawierał dziesięciominutowy przedział, plan i cenę. Dwa wejścia
o 12:09:59 i 12:10:00 albo wybór innego planu tworzyły dwie możliwe do opłacenia
sesje. Sprawdzenie aktywnego abonamentu nie pomagało, dopóki żaden zakup nie
był zakończony. Test przed poprawką zwrócił dwa różne adresy zamiast jednego.

`ProbaZakupu` jest pojedynczym slotem firmy (OneToOne). Przechowuje UUID próby,
niezmienne parametry żądania, czas rozpoczęcia i odzyskany identyfikator sesji.
Nie przechowuje danych karty ani kluczy Stripe i nie przyznaje dostępu do planu.
Parametry mogą zawierać adres e-mail użyty przy zakupie. Wiersz podlega kopii
aplikacji, znika razem z firmą, a następny zakup zastępuje poprzednie parametry.

1. Slot i parametry są zatwierdzane przed wywołaniem tworzącym sesję w Stripe.
   `atomic(durable=True)` odrzuca próbę objęcia całości transakcją nadrzędną.
2. Krótka blokada wiersza slotu serializuje zakupy. Konkurujące żądanie dostaje
   409 i może ponowić; blokada nie obejmuje Tenant używanego przez czat i limity.
3. Ponowienie po utracie odpowiedzi lub błędzie bazy używa tego samego UUID
   i dokładnie tych samych parametrów, również po zmianie e-maila lub konfiguracji.
4. Identyfikator odpowiedzi create jest zapisywany osobno. Aktualny stan jest
   czytany przez retrieve: idempotentny replay może zawierać dawną odpowiedź
   `open`, mimo że sesja została później opłacona lub wygasła.
5. Ten sam plan i cena zwracają istniejący adres. Zmiana planu/ceny wymaga
   potwierdzonego `expired`. Błąd wygaszenia nie uprawnia do nowej sesji.
6. `complete` blokuje kolejny zakup także bez webhooka. Dopiero odczyt Stripe
   potwierdzający `canceled` lub `incomplete_expired` dopuszcza nowy zakup.
   Nie anulujemy abonamentów ani nie zwracamy pieniędzy automatycznie.

Po 23 h nie ponawiamy tworzenia sesji o nieznanym identyfikatorze. Pamięć
idempotencji Stripe jest ograniczona (co najmniej 24 h), więc kolejne użycie
tego samego klucza po jej usunięciu mogłoby utworzyć drugi zakup. Znana sesja
jest nadal sprawdzana przez retrieve niezależnie od jej wieku.

Wywołania biblioteki Stripe mają timeout HTTP 10 s ustawiony przy starcie API.
Limit dotyczy pojedynczego wywołania, nie całego żądania z kilkoma operacjami.
Odpowiedź niepewna to bezpieczna odmowa, a nie drugi link płatności.

## Wdrożenie - wymaga kontrolowanego przełączenia

Zmiana dodaje migrację `accounts.0041_proba_zakupu`. Nie wymaga nowych sekretów,
usług ani wydatków infrastrukturalnych. Przed wdrożeniem:

1. Odebrać CI oraz testy w Stripe test mode na osobnym koncie/środowisku.
2. Uzgodnić krótkie okno przełączenia. Zablokować nowe zakupy i rejestracje
   kierowane do starej wersji, zakończyć jej trwające żądania, dopiero potem
   uruchomić migrację. Standardowe nakładanie się starego i nowego procesu
   podczas deployu nie spełnia tego warunku.
3. Migracja zapisuje sloty istniejących firm do jednorazowego przeglądu.
   Przy pierwszym zakupie nowy kod sprawdzi sesje utworzone w ostatniej dobie
   przed migracją. Sesja Checkout jest otwarta najwyżej 24 h. Dla własnej firmy
   wygasi stare otwarte sesje; cudzych i trybu innego niż subscription nie dotknie.
   Uwzględnia też dawne sesje tworzone po customer_email bez znanej kartoteki.
4. Pełne przejrzenie maksymalnie 500 sesji jest wymagane przed nowym zakupem.
   Przekroczenie limitu, awaria odczytu lub nieznany stan oznaczają odmowę 503,
   nie pominięcie kontroli. Przy większym ruchu operator musi wcześniej uzgodnić
   stan starych sesji; nie wolno bez dowodu ustawić flagi kontroli jako wykonanej.
5. Zakończona stara sesja wymaga potwierdzenia stanu jej subskrypcji. Sprawdzić
   także wcześniejsze aktywne abonamenty i duplikaty w Stripe; ten mechanizm
   nie jest pełnym uzgodnieniem wszystkich historycznych płatności (to A02).
6. Wdrożyć zgodny kod web/workera, sprawdzić migracje i `/health/`, odblokować
   zakupy. Nie zostawiać aktywnych procesów starego kodu obsługujących Checkout.

Nie usuwać tabeli i nie cofać migracji po pierwszej próbie zakupu nowym kodem.
Przy awaryjnym wycofaniu wersji zachować tabelę i zamknąć endpoint zakupu,
aż znów będzie obsługiwany przez bezpieczny kod. Dawny kod ignoruje slot
i ponownie dopuszcza dwa zakupy. Pozostałe funkcje aplikacji można odbierać
osobno, bez otwierania sprzedaży.

## Odzyskanie wyniku nieznanego od ponad 23 h

Nie kasować slotu, nie zmieniać UUID i nie czyścić parametrów, aby „odblokować”
klienta. Brak lokalnego identyfikatora nie dowodzi braku sesji lub obciążenia.

Operator odczytuje UUID bieżącej próby z bazy i odnajduje jej sesję w Stripe
po `metadata.checkout_attempt` oraz `metadata.tenant_id`, w tym samym trybie
test/live i koncie Stripe. Następnie:

```text
python manage.py uzgodnij_checkout --tenant 123 --sesja cs_test_...
python manage.py uzgodnij_checkout --tenant 123 --sesja cs_test_... --zapisz
```

Pierwsza komenda wyłącznie sprawdza. Druga przypina identyfikator po weryfikacji
firmy, UUID aktualnej próby, trybu subscription i statusu. Nie tworzy ani nie
anuluje płatności. Kolejne wejście klienta sprawdzi bieżący stan Stripe.
Nie można przypiąć sesji innej firmy, dawnej próby ani podmienić znanego ID.

Jeżeli sesji nie da się odnaleźć (np. pierwsze żądanie miało niepoprawną cenę),
potrzebny jest ręczny przegląd żądań i subskrypcji Stripe. Kod celowo nie udostępnia
automatycznego resetu niepewnego zakupu. Przy odtworzeniu starszej kopii bazy
także uzgodnić zakupy ze Stripe przed ponownym otwarciem sprzedaży.

## Odbiór

- Dwie karty, dwa plany, granica 599/600 sekund: najwyżej jeden otwarty zakup firmy.
- Timeout create po sukcesie, błąd zapisu ID, utrata odpowiedzi expire, powtórzenie
  z innym e-mailem: nie powstaje drugi możliwy do opłacenia zakup.
- Płatność przed webhookiem i podczas wygaszania: nowy zakup jest odrzucony.
- Replay create zwracający dawny stan open: decyduje nowy retrieve.
- Anulowany abonament, wygaśnięta sesja, druga firma: poprawna droga nowego zakupu.
- Stare sesje i operator: paginacja, niepełna lista, obca firma, zgodny UUID,
  dry-run oraz zapis powiązania.

Źródła kontraktu API: [idempotencja](https://docs.stripe.com/api/idempotent_requests),
[tworzenie sesji](https://docs.stripe.com/api/checkout/sessions/create),
[wygaszanie](https://docs.stripe.com/api/checkout/sessions/expire).

## Częściowy odbiór integracyjny — 2.10.2026

Rzeczywiste Stripe test mode, zakres zaliczonych prób, 76 testów regresyjnych
i nadal otwarte warunki operacyjne opisuje [protokół A01/A02](odbior-a01-a02-2026-10-02.md).
Nie utożsamiamy lokalnego replay webhooka i outboxa z dostarczeniem HTTPS/SMTP.
