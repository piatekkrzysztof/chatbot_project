"""Lekka próba rzeczywistego wykonania zadania, odczytywana niezależnie przez web."""

import math
from datetime import UTC, datetime

from celery import shared_task
from django.utils import timezone

from accounts.models import PrzebiegMonitora
from chatbot_project.monitoring_zadan import NAGLOWEK, PROG_SEKUND


@shared_task(bind=True, ignore_result=True, soft_time_limit=10, time_limit=15)
def potwierdz_przebieg(self):
    # Wywołanie lokalne/eager nie dowodzi działania brokera ani workera.
    if self.request.called_directly or self.request.is_eager:
        return
    stamp = (self.request.headers or {}).get(NAGLOWEK)
    if type(stamp) not in (int, float) or not math.isfinite(stamp):
        return
    if not 0 <= timezone.now().timestamp() - stamp <= PROG_SEKUND:
        return
    wyslano = datetime.fromtimestamp(stamp, tz=UTC)
    PrzebiegMonitora.objects.get_or_create(pk=1, defaults={"wyslano_at": wyslano})
    # Spóźnione/równoległe potwierdzenie nie cofa zegara nowszej próby.
    PrzebiegMonitora.objects.filter(pk=1, wyslano_at__lt=wyslano).update(wyslano_at=wyslano)
