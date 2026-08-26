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

# Broker był zdefiniowany wyłącznie w prod.py. W dev nigdy to nie bolało, bo
# zadania i tak wykonywały się w miejscu — ale w chwili, gdy ktoś uruchomi
# prawdziwego workera (robi to docker-compose), Celery nie widzi żadnej
# konfiguracji i wraca do swojego domyślnego brokera, czyli RabbitMQ.
# Worker zalewał wtedy logi:
#   consumer: Cannot connect to amqp://guest:**@127.0.0.1:5672//
CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL

# Tryb inline włączamy tylko wtedy, gdy nikt nie wskazał brokera. Bez tego
# warunku stos z docker-compose byłby wewnętrznie sprzeczny: stoi w nim worker,
# a wszystkie zadania i tak wykonywałyby się w procesie web, więc worker nie
# miałby czego robić i nikt by nie zauważył, że kolejka jest zepsuta.
CELERY_TASK_ALWAYS_EAGER = not os.getenv("REDIS_URL")

# Bez tego Celery w trybie eager POŁYKA wyjątki z zadań — chowa je w wyniku
# zamiast rzucić. Zadanie, które wywalało się w testach, wyglądało wtedy
# dokładnie tak samo jak takie, które przeszło: brak fragmentów w bazie
# i żadnego śladu dlaczego. To ta sama cicha awaria, którą tępimy
# w kolejce produkcyjnej.
CELERY_TASK_EAGER_PROPAGATES = True

# Modyfikujemy odziedziczoną konfigurację zamiast podmieniać cały słownik.
# Przepisany w całości gubił po cichu każdy klucz dodany później w base —
# tak zniknęło kiedyś JWT, a potem klasa schematu OpenAPI.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_CLASSES": [
        *REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"],
        "rest_framework.throttling.ScopedRateThrottle",
    ],
}

# Ciasteczko z refresh tokenem jest doklejane automatycznie, wiec zapytania
# z panelu musza chodzic z poswiadczeniami. Przy wlaczonych poswiadczeniach
# gwiazdka w Access-Control-Allow-Origin jest zabroniona przez specyfikacje,
# a przegladarka odrzuca wtedy CALA odpowiedz -- panel wyglada, jakby backend
# nie odpowiadal. Dlatego lokalnie tez wymieniamy adresy z nazwy zamiast
# zostawiac odziedziczone z base CORS_ALLOW_ALL_ORIGINS.
#
# Przy okazji zawezenie: z wlaczona gwiazdka i poswiadczeniami dowolna
# odwiedzona strona mogla wyslac uwierzytelnione zapytanie do backendu
# stojacego na localhoscie developera.
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    FRONTEND_URL.rstrip("/"),
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    # Port testow przegladarkowych frontendu (playwright.config.ts)
    "http://localhost:3100",
]
CORS_ALLOWED_ORIGINS = list(dict.fromkeys(CORS_ALLOWED_ORIGINS))
CSRF_TRUSTED_ORIGINS = list(CORS_ALLOWED_ORIGINS)
