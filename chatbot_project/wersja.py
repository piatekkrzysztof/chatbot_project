"""
Numer wersji: jedno miejsce.

Po co, skoro to nie jest biblioteka
-----------------------------------
Do dzisiaj nie dawało się odpowiedzieć na pytanie „co jest na produkcji".
`/health/` mówiło, że usługa żyje, ale nie czym jest. Przy zgłoszeniu od
klienta pierwszy krok - ustalenie, czy on w ogóle ma już poprawkę - wymagał
porównywania commitów z datą wdrożenia w panelu Rendera.

Numer jest wystawiony w `/health/`, więc `curl` na ten adres odpowiada na to
pytanie w jednej linii.

Dlaczego publicznie
-------------------
Wersja mówi napastnikowi, co u nas stoi. Przy gotowym silniku CMS byłby to
konkretny trop do listy podatności; tutaj nie ma czego szukać - to jest kod
pisany na miejscu i nie ma bazy CVE dla „Sm-art chatbot 1.0.0". Korzyść
operacyjna z jednoznacznej odpowiedzi „co jest wdrożone" przewyższa to,
czego się z tej liczby dowie ktoś obcy.

Identyfikator commitu zostaje natomiast w logu, nie w odpowiedzi HTTP. Ten już
wskazuje konkretny stan repozytorium i nie ma powodu, żeby podawać go komuś,
kto tylko odpytuje adres.

Kiedy podnosić
--------------
Wersjonowanie semantyczne, liczone z punktu widzenia KLIENTA, nie kodu:

  • poprawka (1.0.x) - naprawa błędu, nic nowego do nauczenia się,
  • mniejsza (1.x.0) - nowa możliwość albo widoczna zmiana w panelu,
  • większa (x.0.0) - zmiana, po której coś, co klient miał skonfigurowane,
    przestaje działać tak samo. Wymiana fragmentu na stronie, zmiana kontraktu
    API widgetu, usunięcie ekranu.

Podniesienie wersji idzie w tym samym commicie co wpis w CHANGELOG.md.
Rozdzielone rozjeżdżają się przy pierwszym pośpiechu.
"""

WERSJA = "1.0.0"
