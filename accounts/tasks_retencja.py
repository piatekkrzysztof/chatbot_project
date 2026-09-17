"""
Nocne sprzątanie po okresach przechowywania.

Na istniejącym workerze, bez nowej usługi - beat już chodzi w `celery-worker`
i od dawna sprząta rozmowy. Kwadrans po tamtym zadaniu, żeby dwa sprzątania nie
zaczynały się w tej samej minucie na jednej bazie.

Zadanie loguje, co usunęło. Przy zerach też: cisza w logu nie odróżnia
przebiegu, który nic nie znalazł, od przebiegu, którego nie było - a to jest
ta sama pomyłka, którą popełnił monitor kopii.
"""

import logging

from celery import shared_task

from accounts import retencja

logger = logging.getLogger(__name__)


@shared_task
def sprzataj_retencje():
    wyniki = retencja.usun_wszystko()
    logger.info(
        "Retencja: usunięto %s wierszy (%s)",
        sum(wyniki.values()),
        ", ".join(f"{klucz}={ile}" for klucz, ile in sorted(wyniki.items())),
    )
    return wyniki
