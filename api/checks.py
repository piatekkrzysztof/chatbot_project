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


@register()
def trusted_proxy_depth(app_configs, **kwargs):
    """
    Ostrzeżenie o nierozpoznanym adresie odwiedzającego za proxy.

    Na produkcji ruch idzie przez serwery pośredniczące (na Renderze:
    Cloudflare i load balancer), więc REMOTE_ADDR to adres proxy, nie klienta.
    Przy TRUSTED_PROXY_DEPTH=0 wszyscy odwiedzający zlewają się w jedną
    tożsamość, a to psuje dwie rzeczy naraz: identyfikator rozmówcy przestaje
    cokolwiek odróżniać, a limit na odwiedzającego po kilkunastu zapytaniach
    zablokowałby widget wszystkim klientom jednocześnie.
    """
    if settings.DEBUG:
        return []

    if getattr(settings, "TRUSTED_PROXY_DEPTH", 0) > 0:
        return []

    return [
        Warning(
            "Adres odwiedzającego nie jest odczytywany zza proxy.",
            hint=(
                "Ustaw TRUSTED_PROXY_DEPTH na liczbę serwerów pośredniczących "
                "(na Renderze: 2). Przy 0 wszyscy odwiedzający wyglądają jak "
                "jeden adres, więc limit na odwiedzającego zablokuje widget "
                "wszystkim naraz. Wartość sprawdzisz na /api/diagnostyka/adres/."
            ),
            id="api.W002",
        )
    ]
