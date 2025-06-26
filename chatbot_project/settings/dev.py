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

# tu możesz nadpisywać, np.
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
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
