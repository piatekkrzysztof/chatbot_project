# Nota do projektu polityki prywatności

Dokument towarzyszy [projektowi polityki](polityka-prywatnosci-projekt.md).
Projekt jest napisany tak, żeby dało się go opublikować bez zmian; ta nota
zbiera wszystko, co w nim jest założeniem albo wyborem wymagającym
potwierdzenia. Nie jest częścią polityki i nie jest do publikacji.

**Skąd pochodzą fakty.** Każda liczba, okres i dostawca w projekcie jest
sprawdzony w kodzie albo w [przepływach danych](przeplywy-danych.md), stan na
17.11.2026. Tego prawnik nie musi weryfikować; lista źródeł jest na końcu.
Do weryfikacji są kwalifikacje prawne poniżej.

## A. Do rozstrzygnięcia przez prawnika

Kolejność od najważniejszej.

### A1. Przekazywanie danych poza EOG (punkt 9)

Projekt podaje formułę ogólną: decyzja o odpowiednim stopniu ochrony dla
dostawców uczestniczących w ramach ochrony danych UE-USA albo standardowe
klauzule umowne. **Nie sprawdzono, który mechanizm dotyczy którego dostawcy
ani czy zawarte z nimi umowy powierzenia go obejmują.** Do sprawdzenia dla
każdego z: Render, Vercel, Cloudflare, OpenAI, Stripe, Resend, Sentry, Google.

- Jeśli wszyscy są objęci jednym z dwóch mechanizmów: punkt 9 zostaje.
- Jeśli któryś nie jest: punkt 9 trzeba zmienić albo dostawcę wymienić.
- Warto rozważyć, czy zamiast formuły ogólnej nie dodać kolumny w tabeli
  z punktu 8 (kraj i mechanizm dla każdego dostawcy).

To ta sama otwarta sprawa co kolumna „Podstawa przekazania" w załączniku B
[umowy powierzenia](umowa-powierzenia.md). Jedno ustalenie zamyka oba miejsca.

### A2. Podział ról przy kontach zespołu (punkty 4 i 5)

Projekt przyjmuje za umową powierzenia (§ 2 i załącznik A):

- dane osoby zakładającej konto firmy i dane do faktury: agencja jest
  administratorem,
- dane osób zaproszonych do zespołu klienta: agencja jest podmiotem
  przetwarzającym, administratorem jest klient.

Do potwierdzenia, czy ten podział jest właściwy także dla danych
bezpieczeństwa osób z zespołu (dziennik działań z adresem IP, sesje). Można
bronić stanowiska, że w tym zakresie agencja jest odrębnym administratorem
(własny interes w bezpieczeństwie platformy). Zmiana wymagałaby korekty
punktu 5 i załącznika A umowy.

### A3. Podstawy prawne (punkty 3, 4 i 6)

Przyjęte w projekcie:

| Cel | Podstawa w projekcie |
|---|---|
| Odpowiedź na zapytanie z formularza | art. 6 ust. 1 lit. b |
| Dalsza korespondencja, wykazanie jej przebiegu | lit. f |
| Marketing | lit. a (zgoda) |
| Konto, świadczenie usługi, wiadomości systemowe i raporty | lit. b |
| Faktury | lit. c |
| Dziennik działań, sesje, limity prób logowania | lit. f |
| Roszczenia | lit. f |
| Rozmowy z botem na stronie agencji | lit. f, a po zostawieniu kontaktu lit. b |

Do sprawdzenia w szczególności:

- czy cotygodniowy raport e-mail i powiadomienie o każdej rozmowie (obie
  funkcje klient włącza sam w ustawieniach) mieszczą się w lit. b,
- czy dla rozmów z botem na stronie agencji lit. f jest wystarczająca, skoro
  odwiedzający może wpisać dane szczególnej kategorii (projekt prosi w punkcie
  6, żeby tego nie robił; system ich nie rozpoznaje ani nie blokuje).

### A4. Sztuczna inteligencja (punkt 7)

Projekt informuje, że odpowiada program, że odpowiedź może być błędna i że
pytanie trafia do OpenAI. Stwierdza brak decyzji w rozumieniu art. 22 RODO
i brak profilowania - zgodnie z kodem: wynik rozmowy nie steruje niczym poza
samą odpowiedzią i propozycją zostawienia kontaktu.

Obowiązek poinformowania, że rozmowa jest z systemem AI (art. 50 rozporządzenia
o sztucznej inteligencji), jest realizowany w samym oknie czatu: pod nazwą
w nagłówku stoi stały napis „Asystent AI · odpowiada automatycznie"
(`components/widget/chrome.tsx` w repozytorium panelu). Do oceny, czy to
oznaczenie i punkt 7 polityki razem wystarczają.

### A5. Stripe jako odrębny administrator (punkt 8)

Projekt stwierdza, że Stripe przetwarza dane płatności także jako odrębny
administrator. Do potwierdzenia z warunkami Stripe.

### A6. Okres przechowywania faktur (punkt 4)

Przyjęto 5 lat od końca roku, w którym upłynął termin płatności podatku. Do
potwierdzenia z księgowością.

### A7. Formularz kontaktowy: „nie dłużej niż 5 lat" (punkt 3)

Poprzednia wersja polityki podawała „okres wynikający z przepisów
o archiwizacji dokumentów (do 5 lat)". Projekt zastępuje to terminem
przedawnienia roszczeń z górną granicą 5 lat. Do potwierdzenia, czy granica
jest właściwa.

### A8. Zobowiązania, które polityka składa

- Punkt 14: „o istotnych zmianach poinformujemy klientów e-mailem". System nie
  ma do tego osobnej funkcji; byłaby to wiadomość wysyłana ręcznie. Umowa
  powierzenia przewiduje 30 dni wyprzedzenia przy zmianie podprzetwarzającego.
- Punkt 9: udostępnienie kopii zabezpieczeń na żądanie.
- Punkt 11: odpowiedź w ciągu miesiąca.

## B. Do potwierdzenia przez właściciela przed publikacją

Fakty, których nie da się sprawdzić w kodzie chatbota.

| # | Założenie w projekcie | Gdzie | Co zrobić, jeśli nieprawda |
|---|---|---|---|
| B1 | Administrator to „SM-art Agencja", adres i NIP jak w dotychczasowej polityce | punkt 1 | wpisać pełną nazwę z CEIDG albo KRS |
| B2 | Adres do spraw danych: `krzysztof@agencjasm-art.pl` (dotychczasowa polityka podawała prywatną skrzynkę Gmail; panel podaje adres w domenie agencji) | punkt 1 | wpisać właściwy; ważne, żeby polityka i panel podawały ten sam |
| B3 | Panel działa pod `panel.agencjasm-art.pl` | wstęp | poprawić adres |
| B4 | Strona agencji korzysta z Google Workspace i Google Analytics (przeniesione z dotychczasowej polityki) | punkt 8 | usunąć albo poprawić ostatni wiersz tabeli |
| B5 | Chatbot działa także na stronie agencji | punkty 2 i 6 | jeśli nie działa: usunąć ostatni wiersz tabeli w punkcie 2 i drugi akapit punktu 6 |
| B6 | Istnieje osobna „Polityka cookies" strony agencji | punkt 12 | jeśli nie istnieje: opisać cookies strony w punkcie 12 |
| B7 | Agencja wysyła marketing wyłącznie za zgodą | punkt 3 | jeśli nie wysyła wcale: usunąć trzeci podpunkt |

## C. Co wyszło przy pisaniu

- **Vercel nie był w żadnym spisie dostawców.** Panel i okno czatu są
  hostowane na Vercelu, więc adres IP każdej osoby otwierającej czat trafia do
  tego dostawcy. Dopisany do projektu polityki, do
  [przepływów danych](przeplywy-danych.md) i do załącznika B umowy
  powierzenia.
- **„Zanonimizowany adres IP" to adres skrócony.** System zeruje ostatnią
  część adresu (ostatni oktet IPv4, końcówkę IPv6). Projekt nazywa to
  „skróconym adresem IP", bo taki adres w połączeniu z innymi danymi nadal
  może być daną osobową. Umowa powierzenia i przepływy danych używają słowa
  „zanonimizowany" - do rozważenia ujednolicenie.
- **Kopie zapasowe a prawo do usunięcia.** Punkt 10 mówi wprost, że usunięcie
  nie obejmuje od razu istniejących kopii (do 365 dni). Do oceny, czy
  sformułowanie jest wystarczające.

## D. Źródła faktów

| Fakt w projekcie | Źródło |
|---|---|
| Lista dostawców i zakres danych | [przepływy danych](przeplywy-danych.md), tabela „Kto przetwarza dane poza naszą bazą" |
| Okresy przechowywania | [przepływy danych](przeplywy-danych.md), tabela „Dane osobowe i czas przechowywania" |
| Domyślne 90 dni dla rozmów | `Tenant.data_retention_days` w `accounts/models.py` |
| Skracanie adresu IP | `chat/privacy.py`, funkcja `anonymize_ip` |
| Sesja 14 dni | `REFRESH_TOKEN_LIFETIME` w `chatbot_project/settings/base.py` |
| Pamięć przeglądarki zamiast cookies w oknie czatu | `components/widget/WidgetChat.tsx` i `public/embed.js` w repozytorium panelu |
| Brak analityki i skryptów zewnętrznych w panelu | `package.json` i `app/` w repozytorium panelu |
| Role stron i zakres powierzenia | [umowa powierzenia](umowa-powierzenia.md), § 2 i załącznik A |
