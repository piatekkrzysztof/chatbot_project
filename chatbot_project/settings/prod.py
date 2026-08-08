from .base import *
import os
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration



DEBUG = False

def _csv(name):
    """Lista z zmiennej środowiskowej, bez pustych wpisów po rozdzieleniu."""
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


ALLOWED_HOSTS = _csv("DJANGO_ALLOWED_HOSTS")

# Render sam podaje hostname usługi — dopisujemy go automatycznie, żeby wdrożenie
# nie wymagało ręcznego ustawiania DJANGO_ALLOWED_HOSTS (jego brak daje 400 na
# każdym żądaniu, co wygląda jak awaria aplikacji, a jest tylko konfiguracją).
RENDER_HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if RENDER_HOST and RENDER_HOST not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_HOST)

# Wymagane przez Django 4+, żeby logowanie do /admin/ po HTTPS działało
CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS if host != "*"]

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = _csv("DJANGO_CORS_ALLOWED_ORIGINS")

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

DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"

AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME")
AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME", "eu-central-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = False

# Stripe
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_DEFAULT_PRICE_ID = os.getenv("STRIPE_DEFAULT_PRICE_ID")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


SENTRY_DSN = os.getenv("SENTRY_DSN")

if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,  # ogranicz śledzenie zapytań
        send_default_pii=True,  # pozwala przesłać np. user.id, IP
    )