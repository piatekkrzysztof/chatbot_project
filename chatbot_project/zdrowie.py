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

from django.db import connection
from django.http import JsonResponse

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


def health_check(request):
    baza = _baza_odpowiada()
    broker = _broker_odpowiada()

    if not baza:
        stan = "awaria"
    elif not broker:
        stan = "ograniczony"
    else:
        stan = "ok"

    return JsonResponse(
        {
            # Zachowane pod starą nazwą i ze starą wartością "ok", bo mogą
            # z tego korzystać zewnętrzne czujki skonfigurowane wcześniej.
            "status": "ok" if baza else "error",
            "stan": stan,
            "baza": baza,
            "broker": broker,
        },
        status=200 if baza else 503,
    )
