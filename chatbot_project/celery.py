import os
from celery import Celery
from celery.schedules import crontab

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