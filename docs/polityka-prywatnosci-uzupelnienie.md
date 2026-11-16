# Polityka prywatności agencji: czego brakuje dla chatbota

Lista do uzupełnienia polityki na `agencjasm-art.pl/polityka-prywatnosci`.
Strona główna panelu odsyła do niej od 12.11.2026 (przegląd końcowy, R06),
a polityka w wersji z 1 marca 2025 opisuje wyłącznie formularz kontaktowy
agencji.

**To nie jest opinia prawna ani gotowy tekst polityki.** To spis faktów
z kodu i z [przepływów danych](przeplywy-danych.md), które polityka musi
pokryć. Sformułowania, podstawy prawne i podstawy przekazania danych poza EOG
są do sprawdzenia przez prawnika - tak samo jak we
[wzorze umowy powierzenia](umowa-powierzenia.md).

Stan polityki sprawdzony 16.11.2026.

## Dwie role, które trzeba rozdzielić

Polityka opisuje dziś jedną sytuację: ktoś pisze do agencji. Chatbot dokłada
dwie inne, a w każdej agencja jest kimś innym.

| Czyje dane | Kim jest agencja | Co ma powiedzieć polityka |
|---|---|---|
| Klienci chatbota: osoby zakładające konto i ich zespół | administratorem | pełny opis: jakie dane, po co, jak długo, komu przekazywane |
| Odwiedzający strony klientów, którzy rozmawiają z botem | podmiotem przetwarzającym | że administratorem jest firma, na której stronie działa bot, i to do niej kieruje się żądania |
| Odwiedzający `agencjasm-art.pl`, jeśli bot działa też tam | administratorem | to samo co dla rozmów na stronach klientów, ale w roli administratora |

Trzeci wiersz zależy od tego, czy widget jest osadzony na stronie agencji -
do potwierdzenia przez właściciela.

## Czego w polityce nie ma

### 1. Konto w panelu

- **Dane:** imię i nazwisko, adres e-mail, nazwa firmy, dane do faktury (nazwa,
  NIP, adres), login, skrót hasła, ustawienia logowania dwuetapowego.
- **Cel:** założenie i prowadzenie konta, rozliczenie usługi.
- **Czas:** do usunięcia konta albo firmy; rozpoczęta, niepotwierdzona
  rejestracja 7 dni; zaproszenia do zespołu 30 dni.

### 2. Bezpieczeństwo konta

- **Dane:** dziennik działań w panelu (osoba, adres IP, adres żądania, wynik,
  bez treści), sesje logowania, powiadomienia o zmianie hasła.
- **Cel:** bezpieczeństwo kont i rozliczalność zmian.
- **Czas:** dziennik 12 miesięcy; sesje 24 godziny po wygaśnięciu;
  powiadomienia 90 dni.

### 3. Płatności

- Dane do faktury i adres e-mail konta trafiają do Stripe. Dane karty nie
  przechodzą przez serwery agencji. Kopia danych rozliczeniowych zostaje
  w Stripe także po usunięciu firmy.

### 4. Rozmowy z botem

- **Dane:** treść rozmowy, ocena odpowiedzi, identyfikator rozmówcy będący
  zanonimizowanym adresem IP (pełny adres nie jest zapisywany przy rozmowie).
  Osoba może wpisać w czacie dowolną treść, także dane o zdrowiu czy inne
  dane szczególnej kategorii.
- **Zapytanie kontaktowe:** imię, e-mail lub telefon, treść wiadomości;
  trafia też mailem do firmy, na której stronie działa bot.
- **Czas:** domyślnie 90 dni, o okresie decyduje firma w panelu (może też
  wyłączyć usuwanie); pojedynczą rozmowę firma usuwa na żądanie.

### 5. Odpowiada automat, nie człowiek

- Odpowiedzi tworzy model językowy na podstawie dokumentów firmy.
- Pytanie odwiedzającego i pasujące fragmenty dokumentów są wysyłane do
  OpenAI, żeby powstała odpowiedź.
- Bot nie podejmuje wobec osoby żadnych decyzji i nie tworzy jej profilu.

### 6. Pamięć przeglądarki zamiast plików cookies

Widget nie ustawia plików cookies. Zapisuje w pamięci przeglądarki
odwiedzającego (`localStorage`, `sessionStorage`):

- historię rozmowy i jej identyfikator, żeby rozmowa przetrwała odświeżenie
  strony,
- ustawienia wyglądu widgetu z ostatniej wizyty,
- informację, że odwiedzający zamknął zaczepkę.

Panel dla zalogowanych używa ciasteczka sesji logowania. Punkt 7 polityki
odsyła do osobnej „Polityki cookies" - trzeba sprawdzić, czy opisuje jedno
i drugie.

### 7. Odbiorcy danych

Punkt 5 polityki wymienia hosting, Google Workspace i Google Analytics.
Chatbot korzysta z innych dostawców:

| Dostawca | Co dostaje | Po co |
|---|---|---|
| Render | całość: aplikacja, baza danych, logi | hosting |
| Cloudflare R2 | pliki dokumentów, kopie zapasowe | przechowywanie |
| OpenAI | pytania odwiedzających, fragmenty i treść dokumentów | odpowiedzi i wyszukiwanie |
| Stripe | dane do faktury, e-mail konta | płatności |
| Resend | adresy i treść wiadomości, w tym zapytania kontaktowe | poczta |
| Sentry | błędy i czasy żądań, bez treści rozmów | diagnostyka |

Ta lista musi być zgodna z załącznikiem B umowy powierzenia.

### 8. Przekazywanie danych poza EOG

Polityka nie wspomina o nim wcale, a większość dostawców z tabeli to firmy
amerykańskie. Podstawa przekazania dla każdego z nich jest do ustalenia przez
prawnika - to ta sama otwarta sprawa co w umowie powierzenia.

### 9. Kopie zapasowe i logi

- Pełne kopie zapasowe zawierają wszystkie dane powyżej i są przechowywane
  do 365 dni.
- Logi aplikacji u dostawcy hostingu (z adresami IP) 7 dni; zdarzenia błędów
  30 dni.

Usunięcie konta albo rozmowy nie usuwa ich od razu z istniejących kopii.

## Co w obecnej polityce sprawdzić przy okazji

- **Data:** „Ostatnia aktualizacja: 1 marca 2025".
- **Punkt 5:** czy Google Workspace i Google Analytics są nadal używane.
- **Punkt 6:** adres do żądań to prywatna skrzynka; panel podaje jako kontakt
  adres w domenie agencji. Warto, żeby polityka i panel podawały ten sam.
- **Punkt 3:** dla konta w panelu podstawą będzie wykonanie umowy, dla
  dziennika bezpieczeństwa uzasadniony interes - dobór podstaw do
  potwierdzenia przez prawnika.

## Kolejność

1. Prawnik: podstawy przekazania poza EOG (wspólne z umową powierzenia).
2. Uzupełnienie polityki o punkty 1-9.
3. Aktualizacja daty i sprawdzenie „Polityki cookies".
4. Dopiero potem pierwsza sprzedaż - tak jak przy umowie powierzenia
   (decyzja właściciela z 11.10.2026).
