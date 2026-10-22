"""
Próba Sentry bez publicznego adresu (2.32.6).

Do 2.32.5 próbę robiło się wejściem na `/sentry-debug/`. Adres był publiczny
i bez limitu, a każde wejście kończyło się błędem 500 i zdarzeniem w Sentry -
kto chciał, mógł wyczerpać nim miesięczny limit zdarzeń i oślepić monitoring
do końca miesiąca (audyt 2026-10, P07). Teraz próbę robi polecenie, które
uruchamia tylko ktoś z dostępem do powłoki usługi.
"""

from io import StringIO
from unittest import mock

import pytest
from django.core.management import CommandError, call_command
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_publicznego_adresu_proby_juz_nie_ma():
    odpowiedz = APIClient(raise_request_exception=False).get("/sentry-debug/")

    assert odpowiedz.status_code == 404


def test_polecenie_wysyla_zdarzenie_i_podaje_jego_numer():
    wyjscie = StringIO()
    with (
        mock.patch("sentry_sdk.is_initialized", return_value=True),
        mock.patch("sentry_sdk.capture_message", return_value="abc123") as zgloszenie,
        mock.patch("sentry_sdk.flush") as wyslanie,
    ):
        call_command("sprawdz_sentry", stdout=wyjscie)

    assert zgloszenie.call_args.kwargs["level"] == "error"
    wyslanie.assert_called_once()
    assert "abc123" in wyjscie.getvalue()


def test_bez_wlaczonego_sentry_polecenie_konczy_sie_bledem():
    """Cichy sukces bez Sentry wyglądałby jak działający monitoring."""
    with (
        mock.patch("sentry_sdk.is_initialized", return_value=False),
        mock.patch("sentry_sdk.capture_message") as zgloszenie,
        pytest.raises(CommandError, match="Sentry nie jest włączone"),
    ):
        call_command("sprawdz_sentry")

    zgloszenie.assert_not_called()
