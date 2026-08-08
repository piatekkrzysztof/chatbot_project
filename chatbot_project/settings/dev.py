from .base import *

# Osobna baza od testowej (chatbot_test_db). Współdzielenie jednej sprawiało,
# że praca w przeglądarce zostawiała dane psujące testy i odwrotnie.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DEV_DB_NAME", "chatbot_dev_db"),
        "USER": os.getenv("DEV_DB_USER", "postgres"),
        "PASSWORD": os.getenv("DEV_DB_PASSWORD", "wojaki123"),
        "HOST": os.getenv("DEV_DB_HOST", "localhost"),
        "PORT": os.getenv("DEV_DB_PORT", "5432"),
    }
}

DEBUG = True

# Bez lokalnego Redis/Celery workera zadania wykonują się synchronicznie,
# w tym samym procesie co request — .delay() nie próbuje łączyć się z brokerem.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Modyfikujemy odziedziczoną konfigurację zamiast podmieniać cały słownik.
# Przepisany w całości gubił po cichu każdy klucz dodany później w base —
# tak zniknęło kiedyś JWT, a potem klasa schematu OpenAPI.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_CLASSES": [
        *REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"],
        "rest_framework.throttling.ScopedRateThrottle",
    ],
}
