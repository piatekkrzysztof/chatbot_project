import os

import sentry_sdk
from celery import Celery
from celery.schedules import crontab
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    integrations=[DjangoIntegration(), CeleryIntegration()],
    traces_sample_rate=0.1,
    send_default_pii=True,
)

# Ustawienie domyślnego settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chatbot_project.settings.base")

app = Celery("chatbot_project")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Automatyczne wykrywanie zadań we wszystkich apps
app.autodiscover_tasks()


app.conf.beat_schedule = {
    "crawl-active-website-sources-every-12h": {
        "task": "documents.tasks.website_scheduler.crawl_all_active_sources",
        "schedule": crontab(minute=0, hour="*/12"),  # co 12h
    },
}