import os

from celery import Celery
from celery.schedules import crontab

from chatbot_project.observability import init_sentry

init_sentry()

# Pakiet, nie konkretny moduł. settings/__init__.py wybiera dev albo prod
# na podstawie DJANGO_ENV — tak samo robią manage.py i wsgi.py.
#
# Stało tu "chatbot_project.settings.base", a base.py nie ma ANI JEDNEJ
# nastawy Celery. Na produkcji nie bolało, bo Render podaje
# DJANGO_SETTINGS_MODULE jawnie i setdefault go nie rusza. Bolało dopiero
# lokalnie: worker nie widział żadnego brokera i wracał do domyślnego dla
# Celery, czyli RabbitMQ, zalewając logi
#   consumer: Cannot connect to amqp://guest:**@127.0.0.1:5672//
# Nikt tego nie zauważył, bo w dev zadania i tak wykonywały się w miejscu
# i workera po prostu się nie uruchamiało.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chatbot_project.settings")
os.environ.setdefault("DJANGO_ENV", os.getenv("DJANGO_ENV", "dev"))

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
    # Koniec subskrypcji wycisza chatbota tak samo jak wyczerpany limit
    # wiadomości, ale przez długi czas nie miał żadnego powiadomienia.
    # Codziennie rano, tuż po raporcie tygodniowym, żeby dwie wiadomości
    # nie przychodziły w tej samej minucie.
    # Odmowy widgetu sprawdzamy co godzine, a nie raz na dobe. Awaria
    # z sierpnia trwala okolo doby i znalazl ja przypadek - dobowy odstep
    # bylby od tego przypadku niewiele lepszy. Godzina kosztuje jedno
    # zapytanie i skraca czas do zauwazenia z dnia do kwadransa.
    "odmowy-widgetu-co-godzine": {
        "task": "accounts.czuwanie.sprawdz_odmowy_widgetu",
        "schedule": crontab(minute=5),
    },
    # Cisza widgetu: sygnal z natury dobowy, wiec czestsze sprawdzanie
    # powtarzaloby te sama odpowiedz. Rano, zeby dzien ciszy byl juz pelny.
    "cisza-widgetu-codziennie": {
        "task": "accounts.cisza.sprawdz_cisze_zadanie",
        "schedule": crontab(minute=45, hour=8),
    },
    # Rozmiar bazy wiedzy zmienia sie powoli, wiec raz na dobe wystarczy.
    # Chodzi o uprzedzenie, nie o wykrycie awarii.
    "rozmiar-bazy-wiedzy-codziennie": {
        "task": "accounts.rozmiar_bazy.sprawdz_rozmiary_zadanie",
        "schedule": crontab(minute=0, hour=9),
    },
    "konce-subskrypcji-codziennie": {
        "task": "accounts.tasks_konce.sprawdz_konce_subskrypcji",
        "schedule": crontab(minute=15, hour=8),
    },
}
