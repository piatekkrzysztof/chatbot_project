"""
Pomiar czasu odpowiedzi API (F16, część 3).

Dotąd jedynym źródłem czasów był Sentry, który próbkuje 10% żądań - wolne
żądanie miało więc dziewięć szans na dziesięć, żeby nie zostawić śladu. Nie
dokładamy płatnej usługi: każde żądanie API, które trwało dłużej niż
`WOLNE_ZADANIE_MS`, zostawia jedną linię w logu serwisu (Render).

W linii jest trasa jako wzorzec (`api/documents/<int:pk>/`), a nie adres -
bez identyfikatorów, parametrów zapytania i danych z żądania. Obok czasu
liczba zapytań SQL, bo przy wolnym żądaniu to pierwsze pytanie: baza czy kod.

Czas liczony do zwrócenia odpowiedzi przez widok. Przy odpowiedziach
strumieniowych (czat widgetu, eksport CSV) nie obejmuje wysyłania treści.
"""

import logging
from time import perf_counter

from django.conf import settings
from django.db import connections

logger = logging.getLogger(__name__)


class LicznikZapytan:
    """Wrapper wykonania zapytań - tylko liczy, niczego nie zmienia."""

    def __init__(self):
        self.liczba = 0

    def __call__(self, execute, sql, params, many, context):
        self.liczba += 1
        return execute(sql, params, many, context)


def trasa(request):
    """Wzorzec trasy bez identyfikatorów - albo znacznik, gdy adres nie pasuje do żadnej."""
    dopasowanie = getattr(request, "resolver_match", None)
    if dopasowanie is None or not dopasowanie.route:
        return "(bez trasy)"
    return dopasowanie.route


class PomiarCzasuMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        prog = getattr(settings, "WOLNE_ZADANIE_MS", 0)
        if not prog or not request.path.startswith("/api/"):
            return self.get_response(request)

        licznik = LicznikZapytan()
        start = perf_counter()
        with connections["default"].execute_wrapper(licznik):
            odpowiedz = self.get_response(request)
        milisekundy = (perf_counter() - start) * 1000

        if milisekundy >= prog:
            logger.warning(
                "Wolne żądanie: %s %s -> %s w %.0f ms, zapytań SQL: %s",
                request.method,
                trasa(request),
                odpowiedz.status_code,
                milisekundy,
                licznik.liczba,
            )
        return odpowiedz
