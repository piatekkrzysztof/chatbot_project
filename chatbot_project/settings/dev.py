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

# tu możesz nadpisywać, np.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "api.throttles.APIKeyRateThrottle",
        "api.throttles.SubscriptionRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "chat": "20/min",
        "subscription": "100/min",
    }
}
