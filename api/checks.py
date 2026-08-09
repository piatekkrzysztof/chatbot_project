"""
Ostrzeżenie o limitach żądań liczonych osobno w każdym procesie.

Throttling DRF trzyma liczniki w cache. Domyślny LocMemCache jest lokalny dla
procesu, a gunicorn działa na produkcji w kilku (WEB_CONCURRENCY). Każdy proces
prowadzi wtedy własny licznik, więc realny limit jest tylokrotnie wyższy, ile
jest procesów, i zeruje się przy każdym wdrożeniu.

Zabezpieczenie przed nadużyciem, które przepuszcza czterokrotnie więcej, niż
deklaruje, jest gorsze niż jego brak — bo nie wiadomo, że nie działa.
"""
from django.conf import settings
from django.core.checks import Warning, register


@register()
def per_process_rate_limits(app_configs, **kwargs):
    if settings.DEBUG:
        return []

    if getattr(settings, "USE_SHARED_CACHE", True):
        return []

    return [
        Warning(
            "Limity żądań liczone są osobno w każdym procesie serwera.",
            hint=(
                "Ustaw REDIS_URL, żeby liczniki trafiły do wspólnego cache. "
                "Bez tego przy WEB_CONCURRENCY=4 realny limit jest czterokrotnie "
                "wyższy od skonfigurowanego i zeruje się przy wdrożeniu."
            ),
            id="api.W001",
        )
    ]
