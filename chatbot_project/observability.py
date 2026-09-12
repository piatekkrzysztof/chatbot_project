"""
Inicjalizacja Sentry — w jednym miejscu i tylko na serwerze.

Dotąd zgłaszanie błędów włączało się w dwóch miejscach niezależnie: w prod.py
oraz bezwarunkowo przy imporcie celery.py. Ponieważ lokalny .env zawiera
produkcyjny DSN, wystarczyło uruchomić `manage.py check` przy diagnozowaniu
wdrożenia, żeby wysłać zdarzenie do Sentry i dostać mailem alert o awarii,
której na produkcji nie było.

Alert o nieistniejącym błędzie jest gorszy niż jego brak: uczy ignorować
powiadomienia, a wtedy prawdziwa awaria też zostaje przeoczona.

Render ustawia RENDER i RENDER_EXTERNAL_HOSTNAME. Sprawdzamy oba, bo drugie
dotyczy usług webowych i może nie być ustawione dla workerów.
"""

import logging
import os

logger = logging.getLogger(__name__)


def redact_credentials(event, hint):
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("cookies", None)
    extra = event.get("extra")
    job = extra.get("celery-job") if isinstance(extra, dict) else None
    if isinstance(job, dict):
        job.pop("args", None)
        job.pop("kwargs", None)
    return event


def running_on_server():
    """Czy proces działa na Renderze, a nie na czyjejś maszynie."""
    return bool(os.getenv("RENDER") or os.getenv("RENDER_EXTERNAL_HOSTNAME"))


def init_sentry():
    """
    Włącza zgłaszanie błędów, jeśli jest DSN i jesteśmy na serwerze.

    Zwraca informację, czy Sentry faktycznie wystartowało — przydatne
    w testach i przy diagnozowaniu, dlaczego zdarzenia nie docierają.
    """
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return False

    if not running_on_server():
        logger.info(
            "Pomijam Sentry: uruchomienie lokalne. "
            "Ustaw RENDER=1, jeśli naprawdę chcesz wysyłać stąd zdarzenia."
        )
        return False

    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=dsn,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        before_send=redact_credentials,
        before_send_transaction=redact_credentials,
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
    )
    return True
