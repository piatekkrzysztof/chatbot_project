import os

from celery import Celery
from celery.schedules import crontab

from chatbot_project.observability import init_sentry

init_sentry()

# Ustawienie domyślnego settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chatbot_project.settings.base")

app = Celery("chatbot_project")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Automatyczne wykrywanie zadań we wszystkich apps
app.autodiscover_tasks()


app.conf.beat_schedule = {
    "crawl-active-website-sources-every-12h": {
        "task": "documents.tasks.crawl_all_active_sources",
        "schedule": crontab(minute=0, hour="*/12"),  # co 12h
    },
    # RODO: dane rozmów muszą znikać po okresie retencji ustawionym przez klienta
    "purge-expired-conversations-daily": {
        "task": "chat.tasks.purge_expired_conversations",
        "schedule": crontab(minute=30, hour=3),
    },
    # Poniedziałek rano, przed rozkręceniem się tygodnia: lista pytań, na które
    # bot nie umiał odpowiedzieć, jest do załatwienia w kwadrans i najlepiej
    # zrobić to, zanim przyjdą kolejne. Godzina w Europe/Warsaw (TIME_ZONE).
    "raport-luk-w-wiedzy-co-tydzien": {
        "task": "chat.tasks.wyslij_raporty_tygodniowe",
        "schedule": crontab(minute=0, hour=8, day_of_week=1),
    },
}