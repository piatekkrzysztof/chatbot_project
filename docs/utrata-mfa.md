# Utrata drugiego składnika (MFA) - procedura

**Szkic z 9.10.2026, do akceptacji właściciela.** Miejsca oznaczone
**DO DECYZJI** wymagają rozstrzygnięcia, zanim procedura zacznie obowiązywać.

## Dlaczego to ważne

Drugi składnik chroni konto przed kimś, kto zna hasło. Prośba „zgubiłem
telefon, wyłączcie mi kod” to dokładnie to, co napisałby ktoś, kto ukradł
hasło i chce obejść tę ochronę. Procedura ma więc dwa cele naraz: oddać
dostęp prawdziwemu właścicielowi konta i **nie oddać go nikomu innemu**.
Pomyłka w drugą stronę otwiera rozmowy wszystkich odwiedzających firmy klienta.

Do 9.10.2026 nie było żadnej procedury ani narzędzia - jedyną drogą była
ręczna zmiana w bazie, bez śladu w dzienniku, bez zakończenia sesji i bez
powiadomienia właściciela konta.

## Krok 0 - zanim ktokolwiek zgłosi się do nas

Osoba z włączonym MFA ma **10 kodów zapasowych** (wydanych przy włączaniu).
Każdy działa raz, zamiast kodu z aplikacji, na ekranie logowania. To pierwsza
i właściwa droga - bez udziału obsługi. Po zalogowaniu kodem zapasowym osoba
sama wyłącza i włącza MFA na nowym telefonie (Ustawienia konta →
bezpieczeństwo) i dostaje nowe kody.

Procedura poniżej dotyczy tylko sytuacji, gdy osoba **nie ma ani telefonu,
ani żadnego kodu zapasowego**.

## Krok 1 - gdy w firmie jest inny właściciel

Jeśli konto należy do zespołu, w którym jest **inny właściciel z działającym
dostępem**, najprostsza i najbezpieczniejsza droga nie wymaga nas:

**DO DECYZJI:** czy dajemy właścicielowi firmy możliwość zresetowania MFA
osobie z jego zespołu w panelu? Dziś panel tego nie ma - zmiana roli
i usunięcie osoby tak. Do tego czasu: właściciel może usunąć osobę z zespołu
i zaprosić ją ponownie (nowe konto, bez MFA). Historia działań tej osoby
zostaje w dzienniku pod starym kontem.

## Krok 2 - weryfikacja tożsamości przez obsługę

Gdy osoba jest jedynym właścicielem albo krok 1 nie wchodzi w grę.

1. **Zgłoszenie przychodzi z adresu e-mail konta.** Odpowiadamy wyłącznie na
   ten adres - nie na inny wskazany w treści („piszę z prywatnej skrzynki”).
   Sam mail nie wystarcza: skrzynka mogła wyciec razem z hasłem.
2. **Drugi, niezależny kanał** - przynajmniej jeden z:
   - oddzwonienie na numer telefonu firmy z danych do faktury
     (nie na numer podany w zgłoszeniu);
   - potwierdzenie danych, których nie ma w samym koncie: kwota i data
     ostatniej płatności w Stripe, NIP z danych do faktury, nazwa domeny,
     na której działa widget.
   **DO DECYZJI:** który z tych kanałów jest wymagany, a który wystarczający.
3. **Czas oczekiwania.** **DO DECYZJI:** czy wyłączamy od razu po weryfikacji,
   czy po np. 24 godzinach od zgłoszenia, z mailem „otrzymaliśmy prośbę
   o wyłączenie MFA - jeśli to nie Ty, odpowiedz”. Opóźnienie daje
   prawdziwemu właścicielowi czas na reakcję, gdy prosi ktoś inny, ale
   wydłuża przestój dla prawdziwej osoby.
4. **Odmowa**, gdy: zgłoszenie z innego adresu niż konta; dane z kroku 2 się
   nie zgadzają; zgłaszający naciska na pośpiech albo prosi o zmianę adresu
   e-mail konta przy okazji. Odmowę zapisujemy tak samo jak zgodę.

## Krok 3 - wyłączenie (Render → Shell)

Najpierw na sucho - pokazuje konto, firmę, stan MFA i liczbę sesji:

```sh
python manage.py wylacz_mfa --email OSOBA@FIRMA.PL --zgloszenie "OPIS WERYFIKACJI"
```

Potem to samo z `--wykonaj`. Polecenie, w jednej transakcji:

- usuwa drugi składnik i wszystkie kody zapasowe;
- **kończy wszystkie sesje** tej osoby - ktoś, kto przejął telefon razem
  z zalogowaną kartą, zostaje wylogowany;
- zapisuje wpis w dzienniku firmy („obsługa Sm-art”, `CLI`, opis weryfikacji);
- wysyła osobie mail z ostrzeżeniem „jeśli to nie Ty - zmień hasło i odpowiedz”.

`--zgloszenie` jest obowiązkowe: to jedyny ślad, **na jakiej podstawie**
wyłączyliśmy ochronę. Wpisz kanał, datę i co sprawdzono, np.
„mail 9.10 z adresu konta + oddzwonienie na numer z faktury, NIP zgodny”.
Jeśli mail z ostrzeżeniem nie wyjdzie, polecenie mówi to wprost (kod 1) -
wtedy powiadom osobę innym kanałem.

## Krok 4 - po wyłączeniu

1. Osoba loguje się samym hasłem (najlepiej najpierw je zmienia przez
   „Nie pamiętam hasła”) i od razu włącza MFA ponownie, z nowymi kodami.
2. Sprawdzamy w dzienniku firmy, czy między zgłoszeniem a wyłączeniem nie
   było nietypowych działań na koncie.
3. **DO DECYZJI:** gdzie trzymamy rejestr zgłoszeń (zgody i odmowy) poza
   dziennikiem firmy - np. osobny arkusz z datą, kanałem i decyzją.

## Czego ta procedura nie obejmuje

- Utraty dostępu do **skrzynki e-mail** konta - to zmiana adresu konta,
  osobny i trudniejszy przypadek (**DO DECYZJI**).
- Konta **administratora platformy** (Django admin wymaga MFA osobno).
