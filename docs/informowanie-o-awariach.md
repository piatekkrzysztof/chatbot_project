# Informowanie klientów o awariach

**Decyzje właściciela z 11.10.2026.** Monitor z zewnątrz (UptimeRobot) działa
od 28.09.2026 ([monitoring dostępności](monitoring-dostepnosci.md)) i wykrywa
przerwy. Ten dokument mówi, co i kiedy dowiaduje się klient.

## Zobowiązanie wobec klienta

Bez liczbowego SLA. W regulaminie „dokładamy starań, żeby usługa była
dostępna”, a stan na bieżąco i historia przerw są publiczne. Powód: działa
jedna instancja web; restart, wdrożenie albo awaria dostawcy to przerwa,
której nie da się wykluczyć bez drugiej instancji.

Wewnętrzne cele (99,5% dostępności w miesiącu i inne) są w
[SLO](slo-i-czasy-odpowiedzi.md) - służą do reakcji, nie do obietnic.

## Kanał

**Publiczna strona statusu UptimeRobot** (plan darmowy, ten sam monitor co
alarmy) i link do niej w panelu. Klient sam sprawdza stan; w trakcie awarii
nie piszemy ręcznie do każdego.

## Próg

Aktywnie informujemy o przerwie **powyżej 30 minut**: wpis na stronie
statusu z opisem i przewidywanym czasem powrotu, uzupełniony po
zakończeniu. Krótsze przerwy (restart, wdrożenie) widać na stronie statusu
same, bez opisu.

## Do zrobienia

1. Właściciel zakłada stronę statusu w UptimeRobot na istniejącym monitorze.
2. Link do niej w panelu (stopka i ekran Stan) - po otrzymaniu adresu.
3. Zdanie o dostępności w regulaminie - przy przeglądzie prawnym umowy
   powierzenia.
