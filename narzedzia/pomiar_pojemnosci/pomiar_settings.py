"""Ustawienia pomiaru: produkcyjne, z lokalnym magazynem i bez limitów częstotliwości."""

from chatbot_project.settings.prod import *  # noqa: F403
from chatbot_project.settings.prod import REST_FRAMEWORK, STORAGES

SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
ALLOWED_HOSTS = ["*"]
LIMIT_ODWIEDZAJACEGO = "1000000/hour"
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": dict.fromkeys(
        REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "1000000/hour"
    ),
}
STORAGES = {
    **STORAGES,
    "private_documents": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": "/tmp/prywatne"},
    },
}
CHAT_MAX_CONCURRENT = 1000
