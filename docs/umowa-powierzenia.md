# Umowa powierzenia przetwarzania danych osobowych

Wzór umowy, którą klient (administrator) zawiera ze Sm-art (podmiot
przetwarzający) na podstawie art. 28 ust. 3 RODO.

## Zanim ktokolwiek to podpisze

**Ten dokument nie jest opinią prawną i nie zastępuje prawnika.** Powstał
z tego, co system naprawdę robi: każda liczba, każdy podprzetwarzający i każdy
środek bezpieczeństwa poniżej jest sprawdzony w kodzie albo w
[przepływach danych](przeplywy-danych.md), a nie przepisany z cudzego wzoru.
To czyni go dokumentem prawdziwym, ale nie czyni go poprawnym prawnie.

Do sprawdzenia przez prawnika przede wszystkim: **podstawa przekazywania
danych poza EOG** (załącznik B, kolumna „Podstawa przekazania"). Większość
naszych podprzetwarzających to firmy amerykańskie. To jest największa otwarta
sprawa w tym dokumencie i jedyna, której nie da się rozstrzygnąć czytaniem
naszego kodu.

Lista rzeczy, które musi rozstrzygnąć właściciel, jest na końcu.

---

## § 1. Strony i przedmiot

Umowa zawarta między:

- **Administratorem**: ............................................ (nazwa,
  adres, NIP), dalej „Klient",
- **Podmiotem przetwarzającym**: Sm-art ..........................
  (nazwa, adres, NIP), dalej „Sm-art".

Sm-art świadczy Klientowi usługę chatbota dla jego witryny. Świadcząc ją,
przetwarza dane osobowe, których administratorem jest Klient: dane osób
odwiedzających witrynę Klienta oraz dane osób korzystających z panelu po
stronie Klienta.

Umowa wiąże na czas świadczenia usługi i wygasa razem z nią, z zastrzeżeniem
§ 9 (usunięcie danych).

## § 2. Kto jest kim

Klient jest administratorem. To on decyduje, po co zbiera dane odwiedzających,
jaką treść wgrywa do bazy wiedzy bota i jak długo dane rozmów mają być
przechowywane.

Sm-art jest podmiotem przetwarzającym i przetwarza dane wyłącznie w zakresie
i celu opisanym w załączniku A.

Sm-art pozostaje odrębnym administratorem wobec danych konta Klienta
(nazwa firmy, e-mail właściciela, dane do faktury) w zakresie niezbędnym do
zawarcia i rozliczenia umowy. Tej części umowa powierzenia nie obejmuje.

## § 3. Polecenia Klienta

Sm-art przetwarza dane osobowe wyłącznie na udokumentowane polecenie Klienta.
Za takie polecenie uważa się:

1. samą umowę wraz z załącznikami,
2. ustawienia, które Klient wprowadza w panelu (okres przechowywania danych
   rozmów, treść bazy wiedzy, lista osób mających dostęp, adres powiadomień),
3. odrębne żądania kierowane na adres kontaktowy Sm-art.

Jeżeli polecenie Klienta w ocenie Sm-art narusza RODO albo inne przepisy
o ochronie danych, Sm-art niezwłocznie informuje o tym Klienta i może
wstrzymać jego wykonanie do czasu wyjaśnienia.

Sm-art nie przekazuje danych osobowych do państwa trzeciego poza przypadkami
opisanymi w załączniku B, chyba że obowiązek taki nakłada prawo. W takim
przypadku Sm-art informuje Klienta przed przetwarzaniem, o ile prawo tego nie
zakazuje.

## § 4. Poufność

Do danych osobowych Klienta dopuszczane są wyłącznie osoby, które zobowiązały
się do zachowania poufności albo podlegają ustawowemu obowiązkowi zachowania
tajemnicy. Zobowiązanie obowiązuje także po ustaniu współpracy z Sm-art.

Sm-art zapewnia, że osoby te mają dostęp wyłącznie w zakresie niezbędnym do
wykonania zadania.

## § 5. Bezpieczeństwo

Sm-art stosuje środki techniczne i organizacyjne opisane w **załączniku C**.
Załącznik jest częścią umowy i wymienia środki faktycznie wdrożone, nie
planowane.

Sm-art może zmienić poszczególne środki, pod warunkiem że poziom
bezpieczeństwa nie ulegnie obniżeniu.

## § 6. Podprzetwarzający

Klient udziela Sm-art ogólnej zgody na korzystanie z podprzetwarzających.
Aktualna lista stanowi **załącznik B**.

Sm-art informuje Klienta o zamierzonej zmianie - dodaniu lub zastąpieniu
podprzetwarzającego - z wyprzedzeniem **30 dni**, na adres e-mail właściciela
konta. W tym czasie Klient może wnieść sprzeciw. Jeżeli sprzeciw uniemożliwia
świadczenie usługi, każda ze stron może rozwiązać umowę ze skutkiem na koniec
opłaconego okresu, bez konsekwencji dla Klienta.

Sm-art nakłada na każdego podprzetwarzającego obowiązki co najmniej
odpowiadające tym z niniejszej umowy i odpowiada wobec Klienta za jego
działania jak za własne.

## § 7. Pomoc w realizacji praw osób

Sm-art pomaga Klientowi wywiązać się z obowiązku odpowiadania na żądania osób,
których dane dotyczą (rozdział III RODO), w zakresie, w jakim wymaga to
dostępu do systemu Sm-art.

W praktyce Klient robi to sam, bez udziału Sm-art:

- **usunięcie danych jednej osoby**: zakładka Prywatność w panelu przyjmuje
  identyfikator rozmowy i usuwa ją wraz z powiązanymi zapisami. Identyfikator
  jest widoczny przy każdej rozmowie w zakładce Konwersacje,
- **dostęp i przenoszenie**: zakładka Konwersacje pobiera całą historię rozmów
  jako plik CSV,
- **ograniczenie czasu przechowywania**: ustawienie `data_retention_days`
  w panelu; dane starsze znikają automatycznie każdej nocy.

Jeżeli żądanie osoby wykracza poza te możliwości, Sm-art wykonuje je na
polecenie Klienta bez zbędnej zwłoki, nie później niż w **7 dni**.

Żądania kierowane do Sm-art bezpośrednio przez osobę, której dane dotyczą,
Sm-art przekazuje Klientowi i nie odpowiada na nie samodzielnie.

## § 8. Naruszenia ochrony danych

Sm-art zgłasza Klientowi naruszenie ochrony danych osobowych bez zbędnej
zwłoki, nie później niż w **24 godziny** od jego stwierdzenia, na adres e-mail
właściciela konta.

Zgłoszenie zawiera co najmniej: charakter naruszenia, kategorie i przybliżoną
liczbę osób oraz wpisów, których dotyczy, prawdopodobne konsekwencje, środki
zastosowane lub proponowane oraz dane kontaktowe do dalszych pytań. Jeżeli
części informacji nie da się podać od razu, Sm-art podaje je sukcesywnie.

Sm-art pomaga Klientowi w wykonaniu obowiązków z art. 32-36 RODO, w tym
w zgłoszeniu naruszenia organowi nadzorczemu i zawiadomieniu osób, których
dane dotyczą.

Termin 24 godzin liczy się od stwierdzenia naruszenia. Sm-art prowadzi
monitoring opisany w załączniku C, ale nie gwarantuje, że każde naruszenie
zostanie stwierdzone natychmiast po wystąpieniu.

## § 9. Usunięcie danych po zakończeniu

Po zakończeniu świadczenia usługi Sm-art, według wyboru Klienta, zwraca dane
osobowe albo je usuwa wraz z istniejącymi kopiami roboczymi. Wybór Klient
zgłasza w ciągu **30 dni** od zakończenia; brak zgłoszenia oznacza usunięcie.

Zwrot następuje w formie plików CSV (rozmowy, zapytania kontaktowe) oraz
plików dokumentów wgranych przez Klienta.

**Kopie zapasowe są wyjątkiem i Klient musi o nim wiedzieć.** Dane usunięte
z bazy pozostają w zaszyfrowanych kopiach zapasowych do czasu, aż kopia
wypadnie z rotacji: do **365 dni** dla kopii pełnych i **90 dni** dla
dziennych. Kopie nie są w tym czasie wykorzystywane do żadnego innego celu
niż odtworzenie po awarii i podlegają tym samym środkom bezpieczeństwa.

## § 10. Audyt

Sm-art udostępnia Klientowi informacje niezbędne do wykazania spełnienia
obowiązków z art. 28 RODO i umożliwia audyty, w tym inspekcje, prowadzone
przez Klienta lub upoważnionego przez niego audytora.

Audyt odbywa się po uprzednim uzgodnieniu terminu, w godzinach pracy, nie
częściej niż raz w roku - chyba że powodem jest naruszenie ochrony danych albo
żądanie organu nadzorczego, wtedy bez tego ograniczenia.

Zamiast inspekcji Sm-art może przedstawić aktualną dokumentację: niniejsze
załączniki, [opis przepływów danych](przeplywy-danych.md),
[protokół odbioru kopii i odtworzenia](odbior-f21.md) oraz
[kontrakt dostępu](kontrakt-dostepu.md). Jeżeli Klientowi to nie wystarcza,
inspekcja odbywa się mimo to.

## § 11. Postanowienia końcowe

Zmiany umowy wymagają formy dokumentowej. Załączniki A, B i C mogą być
aktualizowane w trybie opisanym w § 6 i § 5.

W sprawach nieuregulowanych stosuje się RODO i prawo polskie.

---

## Załącznik A. Zakres przetwarzania

**Czas trwania:** czas świadczenia usługi.

**Charakter i cel:** udzielanie odwiedzającym witrynę Klienta odpowiedzi na
podstawie bazy wiedzy Klienta, zbieranie zapytań kontaktowych oraz
udostępnianie Klientowi historii rozmów i statystyk w panelu.

**Kategorie osób, których dane dotyczą:**

- osoby odwiedzające witrynę Klienta i korzystające z chatbota,
- osoby, które zostawiły przez chatbota kontakt do siebie,
- osoby po stronie Klienta z dostępem do panelu (właściciel, pracownicy,
  osoby z dostępem tylko do odczytu).

**Kategorie danych osobowych:**

| Kategoria | Skąd | Uwaga |
|---|---|---|
| Treść rozmowy z botem | odwiedzający | osoba może wpisać w czacie cokolwiek, także dane szczególnej kategorii; Sm-art nie ma wpływu na treść |
| Zanonimizowany adres IP jako identyfikator rozmówcy | odwiedzający | pełny adres nie jest zapisywany przy rozmowie |
| Imię, e-mail lub telefon, treść wiadomości | zapytanie kontaktowe | trafia też do skrzynki Klienta |
| Login, e-mail, skrót hasła, drugi składnik, kody zapasowe | panel Klienta | hasła wyłącznie jako skrót |
| Adres IP, ścieżka, metoda, wynik żądania, osoba | dziennik audytowy panelu | bez treści żądań |
| Dane osobowe zawarte w dokumentach wgranych do bazy wiedzy | Klient | o zawartości decyduje wyłącznie Klient |

**Okresy przechowywania:** zgodnie z tabelą w
[przepływach danych](przeplywy-danych.md#dane-osobowe-i-czas-przechowywania).
Dane rozmów, zapytań kontaktowych i logów zużycia usuwane są automatycznie po
okresie ustawionym przez Klienta (`data_retention_days`, domyślnie 90 dni;
wartość 0 wyłącza usuwanie i jest wtedy decyzją Klienta jako administratora).

---

## Załącznik B. Podprzetwarzający

Stan na 29.09.2026. Lista musi być zgodna z tabelą „Kto przetwarza dane poza
naszą bazą" w [przepływach danych](przeplywy-danych.md) - pilnuje tego test
w `chatbot_project/tests/test_umowa_powierzenia.py`.

| Usługa | Co przetwarza | Po co | Podstawa przekazania poza EOG |
|---|---|---|---|
| Render | Całość: API, worker, PostgreSQL, Redis, logi | Hosting | do uzupełnienia |
| Cloudflare R2 | Pliki dokumentów w prywatnym magazynie, pełne kopie zapasowe | Przechowywanie plików | do uzupełnienia |
| OpenAI | Pytania odwiedzających, fragmenty bazy wiedzy, treść dokumentów do wektorów | Odpowiedzi bota i wyszukiwanie | do uzupełnienia |
| Stripe | Dane do faktury, e-mail konta; dane karty nie przechodzą przez Sm-art | Płatności | do uzupełnienia |
| Resend (SMTP) | Adresy i treść wiadomości, w tym dane kontaktowe z zapytań | Poczta | do uzupełnienia |
| Sentry | Błędy i próbki czasu żądań, bez treści zapytań i tokenów | Diagnostyka | do uzupełnienia |

**Kolumna „Podstawa przekazania" jest pusta celowo.** Wpisanie tam czegokolwiek
bez sprawdzenia przez prawnika, na jakiej podstawie każda z tych firm odbiera
dane z EOG i czy nasza umowa z nią to przewiduje, byłoby oświadczeniem
nieprawdy w dokumencie, który klient bierze do swojego audytu.

---

## Załącznik C. Środki techniczne i organizacyjne

Środki faktycznie wdrożone, z odesłaniem do opisu. Załącznik nie wymienia
zamiarów.

**Rozdzielenie danych klientów.** Każde zapytanie do danych jest ograniczone do
firmy pytającego, a każda trasa API ma wpisaną politykę dostępu; test blokuje
dodanie trasy bez polityki. [Kontrakt dostępu](kontrakt-dostepu.md).

**Kontrola dostępu do panelu.** Role właściciel, pracownik i podgląd. Drugi
składnik uwierzytelnienia obowiązkowy dla administratora, potwierdzenie hasłem
przy zmianach bezpieczeństwa, odwoływanie sesji po zmianie hasła i limit czasu
sesji. [Ustawienia bezpieczeństwa](ustawienia-bezpieczenstwa.md),
[odwoływanie sesji](odwolywanie-sesji.md).

**Dziennik audytowy.** Firma, osoba, czas, metoda, ścieżka, wynik i adres IP
dla każdej zmiany oraz dla odczytów wynoszących dane (eksport rozmów, pobranie
dokumentu), także dla odmów. Treści żądań nie są zapisywane nigdy.
Przechowywany 12 miesięcy. [Przepływy danych](przeplywy-danych.md).

**Szyfrowanie i rozdzielenie magazynów.** Pliki dokumentów w prywatnym
magazynie bez publicznego adresu, pobierane wyłącznie przez podpisane odnośniki
o krótkiej ważności. Kopie zapasowe szyfrowane osobnym kluczem, przechowywanym
poza hostingiem; poświadczenia do dokumentów nie dają dostępu do kopii.
[Prywatne pliki i kopie](prywatne-pliki-i-kopie.md).

**Kopie zapasowe i odtwarzanie.** Kopia pełna obejmuje dane i bajty plików,
w jednej migawce transakcyjnej. Odtworzenie przetestowane na rzeczywistych
danych produkcyjnych 17.09.2026: dane i pliki w komplecie, czas odtworzenia
2,49 s, RTO danych około 10 minut, deklarowane RPO do miesiąca.
[Protokół odbioru](odbior-f21.md#wynik-odbioru---17092026).

**Kontrola, czy kopie w ogóle powstają.** Cotygodniowy przebieg poza hostingiem
alarmuje, gdy zabraknie kolejnej kopii. Alarm został wywołany próbnie
i odebrany. [Harmonogram i kontrola kopii](harmonogram-i-kontrola-kopii.md).

**Minimalizacja w usługach zewnętrznych.** Sentry nie dostaje treści zapytań
ani tokenów; identyfikatory w adresach są maskowane. Nieudane próby logowania
zapisują się bez wskazania osoby.

**Ograniczanie nadużyć.** Limity liczby zapytań na firmę i na adres, limit
równoczesnych wywołań AI, limit wielkości i typu wgrywanych plików.

**Monitorowanie dostępności.** Czujka poza hostingiem sprawdza co 5 minut, czy
usługa odpowiada, i alarmuje pocztą. Alarm sprawdzony próbnie 28.09.2026.
[Monitoring dostępności](monitoring-dostepnosci.md).

**Rozdzielenie środowisk i przegląd kodu.** Zmiany trafiają na produkcję przez
przegląd i komplet blokujących kontroli CI; gałąź główna jest chroniona.

---

## Do decyzji właściciela przed podpisaniem

Wartości poniżej są w tekście wpisane jako propozycje. Każda jest zobowiązaniem
handlowym, nie faktem technicznym, więc potwierdza je właściciel.

| § | Co | Propozycja | Dlaczego taka |
|---|---|---|---|
| 6 | Wyprzedzenie przy zmianie podprzetwarzającego | 30 dni | tyle, żeby klient zdążył zareagować, a my nie byli zablokowani przy awaryjnej zmianie dostawcy |
| 7 | Termin na żądanie wykraczające poza panel | 7 dni | klient ma na odpowiedź osobie miesiąc, więc tydzień zostawia mu zapas |
| 8 | Zgłoszenie naruszenia | 24 godziny | klient ma 72 godziny na zgłoszenie do organu; doba zostawia mu dwie na decyzję |
| 9 | Czas na wybór zwrot/usunięcie | 30 dni | krócej byłoby nieuczciwe wobec klienta, który właśnie odszedł |
| 10 | Częstotliwość audytu | raz w roku | bez ograniczenia przy naruszeniu i na żądanie organu |

Poza tym: **forma dokumentu**. Ten plik jest źródłem treści. To, czy klient
podpisuje PDF, czy akceptuje umowę w panelu przy zakładaniu konta, jest osobną
decyzją - druga droga wymaga zapisywania, kto i kiedy zaakceptował którą
wersję, czego dziś nie robimy.
