"""
Widget widzi, ile ma czekać po odmowie - 2.24.1.

Kategoria ryzyka: KOMUNIKAT BEZ TREŚCI. Widget działa w ramce z domeny panelu,
więc dla przeglądarki odpowiedzi API pochodzą z obcej domeny. Nagłówek
Retry-After nie należy do tych, które przeglądarka pokazuje skryptowi bez
zgody serwera. Do 2.24.1 widget przy limicie wiadomości dostawał 429, ale nie
mógł odczytać, ile czekać - i odwiedzający słyszał tylko „spróbuj za kilka minut".
"""

from unittest.mock import patch

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db(transaction=True)

PANEL = "http://localhost:3000"


@pytest.fixture(autouse=True)
def czysty_cache():
    cache.clear()
    yield
    cache.clear()


def zapytaj(tenant):
    return APIClient().post(
        "/api/widget/chat/stream/",
        {
            "message": "Ile kosztuje tort?",
            "conversation_session_id": "cf236f5b-8082-4513-b8a5-7941f4557f10",
        },
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
        HTTP_ORIGIN=PANEL,
        REMOTE_ADDR="203.0.113.7",
    )


def test_limit_odwiedzajacego_pokazuje_przegladarce_retry_after(settings, tenant, subscribtion):
    """Ten test padał przed 2.24.1: Retry-After był wysyłany, ale niewidoczny dla widgetu."""
    settings.CORS_ALLOWED_ORIGINS = [PANEL]
    settings.LIMIT_ODWIEDZAJACEGO = "1/hour"

    with patch("api.views.widget.stream_chat_message", return_value=iter([b"data: {}\n\n"])):
        pierwsza = zapytaj(tenant)
        pierwsza.close()
        druga = zapytaj(tenant)

    assert pierwsza.status_code == 200
    assert druga.status_code == 429
    assert int(druga["Retry-After"]) > 0
    widoczne = [n.strip().lower() for n in druga["Access-Control-Expose-Headers"].split(",")]
    assert "retry-after" in widoczne
