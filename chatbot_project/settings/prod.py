from .base import *
import os

from chatbot_project.observability import init_sentry



DEBUG = False

def _csv(name):
    """Lista z zmiennej środowiskowej, bez pustych wpisów po rozdzieleniu."""
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


def _origins(name):
    """
    Lista adresów pochodzenia. Ukośnik na końcu czyni z adresu ścieżkę, czego
    django-cors-headers nie przyjmuje i przerywa wdrożenie — a kopiując URL
    z paska przeglądarki bardzo łatwo go zabrać ze sobą.
    """
    return [origin.rstrip("/") for origin in _csv(name)]


def _hosts(name):
    """
    Lista nazw hostów. ALLOWED_HOSTS oczekuje samej nazwy — schemat lub ukośnik
    nie pasuje do niczego i objawia się błędem 400 na każdym żądaniu, co wygląda
    jak awaria aplikacji, a jest literówką w konfiguracji.
    """
    hosts = []
    for value in _csv(name):
        host = value.split("://")[-1].strip("/")
        if host:
            hosts.append(host)
    return hosts


ALLOWED_HOSTS = _hosts("DJANGO_ALLOWED_HOSTS")

# Render sam podaje hostname usługi — dopisujemy go automatycznie, żeby wdrożenie
# nie wymagało ręcznego ustawiania DJANGO_ALLOWED_HOSTS (jego brak daje 400 na
# każdym żądaniu, co wygląda jak awaria aplikacji, a jest tylko konfiguracją).
RENDER_HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if RENDER_HOST and RENDER_HOST not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_HOST)

# Wymagane przez Django 4+, żeby logowanie do /admin/ po HTTPS działało
CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS if host != "*"]

CORS_ALLOW_ALL_ORIGINS = False

# CORS dotyczy stron, które odpytują to API z przeglądarki — czyli frontendu,
# nie tego serwera. FRONTEND_URL i tak musi być poprawny (linki w zaproszeniach),
# więc dokładamy go automatycznie: łatwo tu przez pomyłkę wpisać adres backendu,
# co nic nie daje i objawia się zablokowanymi zapytaniami widgetu.
CORS_ALLOWED_ORIGINS = _origins("DJANGO_CORS_ALLOWED_ORIGINS")
if FRONTEND_URL:
    frontend_origin = FRONTEND_URL.rstrip("/")
    if frontend_origin not in CORS_ALLOWED_ORIGINS:
        CORS_ALLOWED_ORIGINS.append(frontend_origin)
    if frontend_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(frontend_origin)

STATIC_ROOT = BASE_DIR / "staticfiles"

CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_REFERRER_POLICY = "strict-origin"
X_FRAME_OPTIONS = "DENY"

# Redis/Celery
CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Magazyn wgrywanych plików: logotypy i awatary widgetu oraz dokumenty klientów.
#
# Dysk kontenera na Renderze jest ulotny — znika przy każdym wdrożeniu. Wcześniej
# stało tu DEFAULT_FILE_STORAGE, które Django 5.1 usunęło i po cichu ignorowało,
# więc pliki mimo pozorów lądowały właśnie na tym dysku. Teraz decyduje STORAGES,
# a wybór zależy od tego, czy podano dane dostępowe.
AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME")
AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME", "auto")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

# Adres API magazynu. Puste = Amazon S3. Cloudflare R2, Backblaze B2 i MinIO
# mówią tym samym protokołem, więc wystarczy wskazać ich endpoint.
AWS_S3_ENDPOINT_URL = os.getenv("AWS_S3_ENDPOINT_URL") or None

# Publiczny adres, spod którego serwowane są pliki. Przy R2 to domena
# r2.dev albo własna subdomena podpięta do kubełka.
AWS_S3_CUSTOM_DOMAIN = os.getenv("AWS_S3_CUSTOM_DOMAIN") or None

AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = None
# Pliki są publiczne (logo widgetu ładuje przeglądarka odwiedzającego), więc
# adresy nie mogą wygasać — podpisane linki psułyby się po kilku godzinach.
AWS_QUERYSTRING_AUTH = False

USE_OBJECT_STORAGE = bool(
    AWS_STORAGE_BUCKET_NAME and AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY
)

STORAGES = {
    "default": {
        "BACKEND": (
            "storages.backends.s3boto3.S3Boto3Storage"
            if USE_OBJECT_STORAGE
            else "django.core.files.storage.FileSystemStorage"
        )
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

# Klucze Stripe definiuje base.py — tutaj nie powtarzamy.
# STRIPE_DEFAULT_PRICE_ID zniknęło razem z drugą implementacją checkoutu:
# jedna cena dla wszystkich planów sprawiała, że kupiony plan zależał od tego,
# którędy klient przyszedł. Ceny są teraz per plan w STRIPE_PRICE_IDS.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


# Zgłaszanie błędów włącza się tylko na serwerze — patrz observability.py
SENTRY_DSN = os.getenv("SENTRY_DSN")
init_sentry()