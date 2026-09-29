"""
Zgłoszenie, że okres próbny trafił do skrzynki, która już go raz dostała.

Okres próbny przysługuje adresowi, a adresów jednej skrzynki jest wiele:
`jan+sklep@gmail.com` i `j.a.n@gmail.com` to jedno pudełko i jeden człowiek.
Nic tego dotąd nie zauważało, więc ta sama osoba mogła brać kolejne 14 dni
i 2000 wiadomości dowolnie długo, a każde z nich kosztuje nas 6-10 zł u OpenAI.

Alarm, nie blokada. Decyzja właściciela z 29.09.2026: konto powstaje normalnie
i okres próbny też. Powód jest prosty - nie wiemy jeszcze, czy to się w ogóle
zdarza, a odmowa uczciwemu klientowi kosztuje więcej niż dziesięć złotych.
Gdy okaże się, że zdarza się regularnie, odmowa jest zmianą jednego miejsca
w `zalozenie_okresu_probnego`.

Dlaczego wiadomość nie zawiera adresu e-mail
--------------------------------------------
Bo do niczego nie jest potrzebny, a alarm to kolejne miejsce, w którym dane
osobowe wyciekają poza bazę - tym razem do skrzynki operatora i na serwer
poczty. Wiadomość podaje numery firm; kto chce zobaczyć adresy, otwiera panel
administracyjny, gdzie taki odczyt zostawia wpis w dzienniku.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

from accounts.czuwanie import adres_operatora

logger = logging.getLogger(__name__)


def _tresc(numer_firmy, wczesniejsze):
    lista = ", ".join(str(pk) for pk in wczesniejsze)
    return "\n".join(
        [
            f"Firma {numer_firmy} dostała okres próbny na skrzynkę, która brała go już "
            f"{len(wczesniejsze)} raz(y).",
            "",
            f"Wcześniejsze firmy tej samej skrzynki: {lista}.",
            "",
            "Adresy różnią się znacznikiem po „+” albo kropkami w Gmailu, więc poczta "
            "z nich wszystkich trafia do jednego pudełka.",
            "",
            "Okres próbny został przyznany normalnie - to jest zgłoszenie, nie blokada. "
            "Jeden okres to 2000 wiadomości, czyli 6-10 zł kosztu modelu.",
            "",
            "Bywa to zupełnie niewinne: ta sama osoba zakłada konto drugiej firmie albo "
            "wróciła po przerwie. Warto zajrzeć, zanim cokolwiek z tym zrobimy.",
        ]
    )


@shared_task
def zglos_powtorny_okres_probny(numer_firmy, wczesniejsze):
    """Zwraca liczbę wcześniejszych firm, żeby wywołanie z konsoli coś mówiło."""
    logger.warning(
        "Okres próbny na skrzynkę, która brała go już wcześniej: firma=%s, wcześniejsze=%s",
        numer_firmy,
        wczesniejsze,
    )
    wyslane = send_mail(
        subject=f"Powtórny okres próbny: firma {numer_firmy}",
        message=_tresc(numer_firmy, wczesniejsze),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[adres_operatora()],
        fail_silently=False,
    )
    if not wyslane:
        # Zero doręczeń bez wyjątku - tak Django kończy wysyłkę do pustej listy
        # odbiorców i tak zachowuje się backend, który po cichu odrzuca wiadomość.
        raise RuntimeError("send_mail zwrócił 0 - zgłoszenie nie zostało doręczone")
    return len(wczesniejsze)
