"""Sygnał publikacji próby: wiek liczymy od wysłania, nie opróżnienia kolejki."""

import time

from celery.signals import before_task_publish

ZADANIE = "accounts.tasks_monitoring.potwierdz_przebieg"
NAGLOWEK = "monitoring_wyslano"
PROG_SEKUND = 180


@before_task_publish.connect(sender=ZADANIE)
def oznacz_probe(headers=None, **kwargs):
    if headers is not None:
        headers[NAGLOWEK] = time.time()
