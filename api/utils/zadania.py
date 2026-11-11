"""
Treść żądania jako obiekt - albo czytelne 400.

Kilka widoków panelu i jeden publiczny czytają pola wprost z `request.data`
(`in`, `.get`, `[...]`), bez serializera. To działa, dopóki treść jest
obiektem JSON. Poprawny JSON bywa jednak listą, napisem albo `null` i wtedy
te same wiersze rzucają `TypeError` albo `AttributeError`: błąd 500 i zdarzenie
w Sentry zamiast odpowiedzi „złe dane". Ten sam wzorzec audyt 2026-10 poprawił
w limicie logowania (P11); tu jest jedno miejsce dla pozostałych widoków.
"""

from collections.abc import Mapping

from rest_framework.exceptions import ValidationError

TRESC_NIE_JEST_OBIEKTEM = "Treść żądania musi być obiektem JSON."


def dane_obiektu(request):
    """`request.data`, o ile jest obiektem; w przeciwnym razie 400."""
    dane = request.data
    if not isinstance(dane, Mapping):
        raise ValidationError({"detail": TRESC_NIE_JEST_OBIEKTEM})
    return dane
