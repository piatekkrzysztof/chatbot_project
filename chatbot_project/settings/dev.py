from .base import *

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "chatbot_test_db",
        "USER": "postgres",
        "PASSWORD": "wojaki123",
        "HOST": "localhost",
        "PORT": "5432",
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
