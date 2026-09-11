# Sesje przeglądarkowe — F15, część 1

Wydanie 2.0.8. Panel wysyła już `credentials: include`, a przeglądarka dopisuje
`Origin` do POST. Backend nie wymaga nowego nagłówka dodawanego przez JavaScript.

## Granice dostępu

- Logowanie, drugi krok MFA, odświeżanie i wylogowanie sprawdzają dokładne
  pochodzenie (schemat, host, port) względem `FRONTEND_URL` i konkretnych wpisów
  `CSRF_TRUSTED_ORIGINS`. Brak `Origin` dopuszcza poprawny `Referer`; brak obu,
  `Origin: null`, błędne adresy i obce subdomeny kończą się 403 przed zmianą sesji.
  Istniejący, ale błędny `Origin` nie przechodzi przez poprawny `Referer`.
  Nie rozszerzamy zaufania o wildcardy ani domeny widgetów z CORS.
- Produkcja zapisuje `__Host-refresh_token`: Secure, HttpOnly, SameSite=Lax,
  Path=/, bez Domain. Serwery panelu i innych subdomen nie otrzymują tego tokenu.
  Lokalnie po HTTP nazwa to `refresh_token_v2`. Znacznik `sesja_panelu` pozostaje
  współdzielony i niesie wyłącznie wartość `1`, bez uprawnień do API.
- Token odświeżania nie wraca w JSON i nie jest przyjmowany z ciała żądania.
  Stary przełącznik `ZWRACAJ_REFRESH_W_TRESCI` nie ma już wpływu na kod.
- Odpowiedzi sesji, także błędy, mają `Cache-Control: no-store`.
  Wylogowanie nie wymaga ważnego access JWT; unieważnia refresh cookie.

Zasada weryfikacji źródła i ograniczenie SameSite pochodzą z
[OWASP CSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).
Origin nie zastępuje hasła/MFA ani tokenu: klient spoza przeglądarki może ten
nagłówek sam ustawić. Skrypty korzystające z endpointów sesji muszą przechowywać
cookies i jawnie podać zaufany Origin; sam refresh w JSON już nie wystarczy.

## Wdrożenie i cofnięcie

1. Sprawdzić, że `FRONTEND_URL` odpowiada rzeczywistemu adresowi panelu oraz
   istniejący `REFRESH_COOKIE_DOMAIN` nadal odpowiada znacznikowi panelu.
   Nie należy poszerzać listy o strony klientów z osadzonym widgetem.
2. Wdrożyć backend i worker tego samego commita. Brak migracji i nowych usług.
3. Użytkownicy zalogują się ponownie: stare cookie `refresh_token` nie jest
   odczytywane. Jest kasowane w dotychczasowej domenie i ścieżce przy logowaniu,
   odświeżeniu lub wylogowaniu. Access JWT działa do swojego wygaśnięcia (15 min).
4. W przeglądarce sprawdzić login z/bez MFA, odświeżenie strony, rotację,
   wylogowanie i powrót na login, bez pętli przekierowań. Sprawdzić 403 z obcej
   subdomeny i brak Domain w nowym cookie. Potwierdzić health i worker.
5. Cofnięcie kodu nie wymaga cofania schematu bazy, ale może ponownie wymagać
   logowania (starszy kod używa innej nazwy cookie).

Nie unieważniamy hurtowo już wydanych JWT w bazie. Stare tokeny wygasają zgodnie
z TTL; usunięcie cookie nie jest kryptograficznym odwołaniem jego kopii.

## Kolejne części etapu

Otwarte: atomowa rotacja przy równoczesnych żądaniach i współpraca wielu kart,
unieważnianie sesji po zmianie hasła/uprawnień, odzyskiwanie konta, ponowne
potwierdzenie hasła przed konfiguracją MFA oraz odbiór działania w produkcji.
Ten PR nie zamyka całego F15/F22 ani audytu komercyjnego.
