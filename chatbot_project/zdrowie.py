"""
Sprawdzenie stanu usługi dla hostingu i monitoringu zewnętrznego.

Poprzednia wersja tej funkcji brzmiała w całości tak::

    def health_check(request):
        return JsonResponse({"status": "ok"})

Odpowiadała „ok" niezależnie od wszystkiego. Przy leżącej bazie danych, przy
wyczerpanych połączeniach, w środku każdej możliwej awarii - zawsze zielono.
Render odpytuje ten adres, żeby zdecydować, czy usługa żyje, a monitoring
zewnętrzny, żeby zdecydować, czy budzić człowieka. Oba dostawały odpowiedź,
która nic nie znaczyła.

Miernik pokazujący zawsze tę samą wartość jest gorszy niż jego brak: bez niego
wiadomo, że się nie wie, a z nim ma się fałszywą pewność.

Co decyduje o kodzie odpowiedzi
-------------------------------
Wyłącznie baza danych. Bez niej nie działa nic - ani panel, ani widget - więc
503 jest wtedy prawdą i Render ma prawo taką instancję wymienić.

Redis i workery świadomie NIE psują kodu odpowiedzi. Gdy stoją, zatrzymują się
zadania w tle, ale panel i czat odpowiadają dalej; ubicie z tego powodu
działającej usługi zamieniłoby częściową awarię w pełną. Stan zadań widać
w treści odpowiedzi oraz - dokładniej, z dowodami z danych - na ekranie
„Stan systemu" w panelu (`api/views/diagnostyka_zadan.py`).

Ten widok jest publiczny, więc nie wpuszczamy do treści komunikatów wyjątków:
mówią za dużo o środku systemu komuś, kto tylko odpytuje adres. Szczegóły idą
do logu.
"""

import logging
import time
from datetime import timedelta

from django.db import connection
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache

from chatbot_project.monitoring_zadan import PROG_SEKUND
from chatbot_project.wersja import WERSJA

logger = logging.getLogger(__name__)


def _baza_odpowiada() -> bool:
    """Najtańsze możliwe zapytanie - chodzi o połączenie, nie o dane."""
    try:
        with connection.cursor() as kursor:
            kursor.execute("SELECT 1")
            kursor.fetchone()
        return True
    except Exception:
        logger.exception("Health check: baza danych nie odpowiada")
        return False


def _broker_odpowiada() -> bool:
    """
    Czy Redis przyjmuje połączenia.

    Bez ponawiania i z krótkim czasem oczekiwania: przy nieosiągalnym brokerze
    domyślne zachowanie Celery to kilka prób z narastającym odstępem, co
    zamieniłoby sprawdzenie stanu w żądanie wiszące kilkadziesiąt sekund -
    a monitoring uznałby ciszę za awarię całej usługi.
    """
    try:
        from chatbot_project.celery import app

        with app.connection() as polaczenie:
            polaczenie.ensure_connection(max_retries=0, timeout=2)
        return True
    except Exception:
        logger.warning("Health check: broker nie odpowiada", exc_info=True)
        return False


#: Jak długo wynik sprawdzenia brokera służy kolejnym żądaniom.
BROKER_PAMIEC_S = 15
_broker_ostatnio: tuple[float, bool] | None = None


def _broker_z_pamieci() -> bool:
    """
    Stan brokera, sprawdzany najwyżej raz na `BROKER_PAMIEC_S` sekund na proces.

    Adres jest publiczny i odpytywany co kilkanaście sekund przez hosting
    i monitoring. Każde żądanie otwierało nowe połączenie z Redisem - więc
    każdy, kto odpytywał ten adres w pętli, zużywał połączenia brokera,
    z których korzystają zadania w tle.
    """
    global _broker_ostatnio
    teraz = time.monotonic()
    if _broker_ostatnio is not None and teraz - _broker_ostatnio[0] < BROKER_PAMIEC_S:
        return _broker_ostatnio[1]
    wynik = _broker_odpowiada()
    _broker_ostatnio = (teraz, wynik)
    return wynik


def _zadania_dzialaja() -> bool:
    from accounts.models import PrzebiegMonitora

    try:
        teraz = timezone.now()
        return PrzebiegMonitora.objects.filter(
            pk=1, wyslano_at__gte=teraz - timedelta(seconds=PROG_SEKUND), wyslano_at__lte=teraz
        ).exists()
    except Exception:
        # Także brak tabeli podczas wdrażania: brak dowodu nie oznacza zdrowia.
        logger.warning("Health check: brak potwierdzenia działania zadań")
        return False


@never_cache
def health_check(request):
    baza = _baza_odpowiada()
    broker = _broker_z_pamieci()
    zadania = baza and _zadania_dzialaja()

    if not baza:
        stan = "awaria"
    elif not broker or not zadania:
        stan = "ograniczony"
    else:
        stan = "ok"

    return JsonResponse(
        {
            # Zachowane pod starą nazwą i ze starą wartością "ok", bo mogą
            # z tego korzystać zewnętrzne czujki skonfigurowane wcześniej.
            "status": "ok" if baza else "error",
            "stan": stan,
            # Odpowiedź na pytanie „co jest na produkcji". Do tej pory nie dało
            # się jej udzielić inaczej niż przez porównywanie commitów z datą
            # wdrożenia w panelu hostingu.
            "wersja": WERSJA,
            "baza": baza,
            "broker": broker,
            "zadania": zadania,
        },
        status=200 if baza else 503,
    )
