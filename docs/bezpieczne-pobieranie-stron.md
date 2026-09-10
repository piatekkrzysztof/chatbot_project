# Pobieranie stron klientów — F06

Wydanie 2.0.2 kieruje import strony, crawler, wyszukiwanie sitemap i komendę
`zmierz_pobieranie` przez `documents.safe_http`. Trafilatura nadal wyodrębnia
tekst, ale nie pobiera już adresów przekazanych przez użytkownika.

## Zasady dostępu

- Wyłącznie HTTP/HTTPS, porty 80 i 443, bez loginu i hasła w URL-u.
- Brak dostępu do adresów prywatnych, lokalnych, link-local, multicast,
  zarezerwowanych i specjalnych zakresów translacji/tunelowania IPv6.
- Każda odpowiedź DNS musi zawierać wyłącznie publiczne adresy. Mieszana lista
  publicznych i prywatnych A/AAAA jest odrzucana w całości.
- Połączenie TCP używa sprawdzonego numerycznego IP, a nagłówek Host i kontrola
  certyfikatu TLS używają oryginalnej domeny. Późniejsza zmiana DNS nie podmienia
  celu połączenia. Preferowany jest IPv4; w tym wydaniu brak ponawiania połączenia
  z kolejnym adresem tej samej domeny po błędzie sieci.
- Przekierowania przechodzą pełną kontrolę adresu i DNS. Nie przekazujemy cookies,
  poświadczeń `.netrc` ani ustawień proxy z otoczenia procesu.
- API odrzuca niebezpieczną składnię i prywatne literały IP przed zapisem.
  DNS sprawdzamy podczas pobierania; domena wskazująca prywatny adres może więc
  zostać zapisana, ale import zakończy się błędem. Stare wpisy w bazie przechodzą
  tę samą kontrolę podczas odświeżania.

Walidacja wszystkich A/AAAA i ponowna kontrola przekierowań odpowiadają zaleceniom
[OWASP dotyczącym SSRF](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html).
Kod dodatkowo przypina połączenie do sprawdzonego IP. Reguły wyjścia sieciowego
na poziomie infrastruktury pozostają osobną warstwą ochrony, do sprawdzenia przy
odbiorze środowiska.

## Limity

| Obszar | Limit |
|---|---|
| Jedno pobranie, łącznie z DNS i przekierowaniami | 20 sekund |
| DNS, połączenie i pojedyncza operacja na sockecie | Do 5 sekund, w ramach pozostałego czasu |
| Jednocześnie oczekujące operacje DNS | 4 na proces; brak nieograniczonej kolejki |
| Przekierowania | 3 |
| Ciało odpowiedzi przed rozpakowaniem | 2 MiB |
| Ciało odpowiedzi gzip po rozpakowaniu | 4 MiB |
| Wspólny budżet pobierania źródła | 60 żądań, 32 MiB danych, 120 sekund |
| Sitemap | 5 plików, również zagnieżdżonych; osobne pobranie robots.txt |
| Strony | 20; crawler do głębokości 2 i kolejka do 20 adresów |

Wspólny budżet obejmuje robots.txt, sitemapy, odkrywanie linków, importy i ich
przekierowania. Zużycie bajtów uwzględnia większy rozmiar po rozpakowaniu.
Limit czasu obejmuje sieć i jest sprawdzany przed kolejnymi żądaniami; nie jest
twardym limitem CPU całego zadania Celery. Przerwany odczyt, zły certyfikat,
niedozwolony adres i przekroczony limit pozostawiają błąd importu.

Obsługiwane są odpowiedzi bez kompresji i gzip oraz pliki sitemap `.xml.gz`.
Uszkodzone i wieloczęściowe strumienie gzip są odrzucane. Parser
[defusedxml](https://pypi.org/project/defusedxml/0.7.1/) odrzuca DTD i encje
zewnętrzne; nie pobiera zależności XML z sieci ani plików lokalnych.

Crawler i wpisy sitemap muszą wskazywać dokładnie tę samą znormalizowaną domenę
co źródło. Zmiana HTTP na HTTPS jest dopuszczalna; `example.com` i
`www.example.com` to różne domeny. Jeśli witryna przekierowuje na `www`, jako
źródło należy podać jej końcowy adres, aby odkrywać wszystkie podstrony.
Pobranie pojedynczej strony może przejść przekierowanie na inną publiczną domenę,
ale linki spoza domeny źródła nie rozszerzają zakresu crawlera.

## Wdrożenie i sprawdzenie

1. Wdrożyć ten sam commit backendu i workera, instalując zaktualizowane
   `requirements.txt`. Nie ma migracji ani nowych sekretów i zmiennych środowiskowych.
2. Na kontrolowanej publicznej stronie sprawdzić import, odświeżenie istniejącego
   źródła i zachowanie treści w bazie wiedzy. Sprawdzić źródło z sitemapą oraz
   źródło obsługiwane przez crawler. Użyć końcowej domeny po przekierowaniu.
3. Sprawdzić, że odrzucony adres daje czytelny błąd i nie nadpisuje dotychczasowej
   wiedzy. Nie testować skanowania sieci wewnętrznej na produkcji.

Testy regresyjne używają syntetycznych odpowiedzi DNS, socketów i HTML/XML;
nie wysyłają żądań na adresy infrastruktury. Obejmują również prawdziwy parser
HTTP biblioteki standardowej, przypinanie IP, SNI/certyfikaty, powolny odczyt,
kompresję, limit wspólnego budżetu i zapis statusu zadania.

Zakres F09 (uploady), F08 (rezerwacje i koszty wiadomości) oraz F23 (formularz
marketingowy) pozostaje do osobnych zmian. Ta poprawka nie zamyka całego etapu 3.
