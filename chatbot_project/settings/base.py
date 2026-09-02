import os
from datetime import timedelta
from dotenv import load_dotenv
from pathlib import Path
from decouple import config, Csv
import dj_database_url
from corsheaders.defaults import default_headers

dotenv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(dotenv_path)

BASE_DIR = Path(__file__).resolve().parent.parent.parent

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")

SECRET_KEY = config("DJANGO_SECRET_KEY")

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_HEADERS = list(default_headers) + ["x-api-key"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    # Uniewaznianie refresh tokenow. Bez tej aplikacji wylogowanie jest
    # tylko gestem po stronie przegladarki: token dalej dziala az do konca
    # swojego zycia, wiec skradziony nie da sie odebrac.
    "rest_framework_simplejwt.token_blacklist",
    "api",
    "accounts",
    "chat",
    "documents",
    "rag",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.TenantMiddleware",
    "accounts.middleware.SubscriptionMiddleware",
    # Za tamtymi dwoma, bo zapisuje firmę rozpoznaną przez TenantMiddleware.
    # Sam zapis dzieje się w process_response, czyli po widoku - wcześniej nie
    # wiadomo ani kto to jest, ani jak żądanie się skończyło.
    "accounts.middleware.DziennikAudytuMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "chatbot_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "api.throttles.APIKeyRateThrottle",
        "api.throttles.SubscriptionRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "chat": "20/min",
        "subscription": "100/min",
        # Nadpisywane przez LIMIT_ODWIEDZAJACEGO; wpis musi istnieć, bo DRF
        # sprawdza obecność scope'u przy starcie
        "visitor": "20/hour",
        # Logowanie. Stawki hojne dla człowieka, ciasne dla maszyny: ktoś, kto
        # pomyli hasło, poprawia je raz albo dwa. Dwie warstwy, bo każda łapie
        # co innego - po adresie jednego napastnika, po koncie rozproszone
        # zgadywanie z wielu adresów.
        "logowanie-ip": "10/min",
        "logowanie-konto": "5/min",
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Sm-art Chatbot API",
    "DESCRIPTION": (
        "API chatbota SaaS. Dwa rozłączne obszary:\n\n"
        "**Widget** (`/api/widget/...`, `/api/widget-settings/`) — wołany z przeglądarki "
        "odwiedzającego stronę klienta, uwierzytelniany nagłówkiem `X-API-Key` "
        "z kluczem firmy. Bez logowania.\n\n"
        "**Panel** (reszta) — wołany przez zalogowanego właściciela lub pracownika, "
        "uwierzytelniany tokenem JWT z `/api/accounts/login/`.\n\n"
        "Klucz API firmy jest publiczny — trafia do kodu osadzanego na stronie klienta. "
        "Nie daje dostępu do panelu ani do danych rozmów, tylko do zadawania pytań "
        "i odczytu ustawień widgetu."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # "role" występuje w kilku serializerach z tym samym zestawem wartości —
    # bez tego generator nadaje im losowo wyglądające nazwy typu Role94aEnum
    "ENUM_NAME_OVERRIDES": {
        "RoleEnum": "accounts.models.UserRole.choices",
    },
    # Endpointy widgetu nie używają JWT, więc automatyczne wykrywanie oznaczałoby
    # je jako wymagające logowania — opisujemy klucz API jawnie.
    "APPEND_COMPONENTS": {
        "securitySchemes": {
            "ApiKeyAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
                "description": "Klucz API firmy, widoczny w panelu w zakładce Widget.",
            }
        }
    },
}

SIMPLE_JWT = {
    # 15 minut zamiast 8 godzin. Token dostepu zyje teraz w pamieci karty
    # przegladarki, a nie w localStorage, wiec odswiezanie jest tanie --
    # a skradziony token jest wart kwadrans, nie caly dzien pracy.
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=14),
    # Kazde odswiezenie wydaje nowy refresh i uniewaznia poprzedni. Dzieki
    # temu token przechwycony i uzyty przez napastnika wylogowuje wlasciciela
    # -- kradziez przestaje byc cicha.
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

# Ciasteczko z refresh tokenem.
#
# Domena z kropka na poczatku, zeby ciasteczko ustawione przez
# api.agencjasm-art.pl doszlo do panel.agencjasm-art.pl. Oba adresy leza pod
# ta sama domena rejestrowalna, wiec zapytania miedzy nimi sa "same-site" --
# dlatego wystarcza SameSite=Lax i nie trzeba stawiac warstwy posredniczacej
# po stronie Next.js.
#
# Lokalnie domena zostaje pusta: ciasteczko ustawione przez localhost:8000
# i tak dojdzie do localhost:3000, bo ciasteczka ignoruja numer portu.
NAZWA_CIASTECZKA_ODSWIEZANIA = "refresh_token"
CIASTECZKO_ODSWIEZANIA_DOMENA = os.getenv("REFRESH_COOKIE_DOMAIN") or None
CIASTECZKO_ODSWIEZANIA_SAMESITE = "Lax"
CIASTECZKO_ODSWIEZANIA_SECURE = False
# Sciezka zawezona do samego odswiezania i wylogowania: ciasteczko nie jest
# doklejane do kazdego zapytania do API, wiec nie wycieka do logow posrednikow
# ani nie powieksza kazdego zadania bez potrzeby.
CIASTECZKO_ODSWIEZANIA_SCIEZKA = "/api/accounts/"

# Drugie ciasteczko: sam znacznik "ta przegladarka ma sesje", bez tokenu.
#
# Po co: ciasteczko z tokenem ma sciezke /api/accounts/, wiec przegladarka nie
# wysyla go pod panel.agencjasm-art.pl -- a wlasnie tam Next.js musi wiedziec,
# czy przepuscic trase, zanim cokolwiek wyrenderuje. Bez tego chroniona tresc
# miga na ekranie, zanim kod po stronie klienta zdazy przekierowac.
#
# Bezpieczenstwo: to ciasteczko nie otwiera niczego. Podrobienie go daje tyle,
# ze panel sie wyrenderuje i natychmiast dostanie 401 z API, bo prawdziwym
# strażnikiem jest token, nie ono. Jest mimo to HttpOnly, bo czyta je serwer
# Next.js z naglowka zadania, a nie skrypt w przegladarce -- HttpOnly blokuje
# document.cookie, nie odczyt po stronie serwera.
NAZWA_CIASTECZKA_SESJI = "sesja_panelu"

# Przejsciowo logowanie zwraca refresh takze w tresci odpowiedzi, zeby
# obecny frontend dzialal do czasu swojego wdrozenia. Do usuniecia zaraz
# po nim -- refresh w tresci trafia do localStorage, czyli tam, skad ta
# przebudowa go zabiera.
ZWRACAJ_REFRESH_W_TRESCI = os.getenv("ZWRACAJ_REFRESH_W_TRESCI", "1") == "1"

WSGI_APPLICATION = "chatbot_project.wsgi.application"
ASGI_APPLICATION = "chatbot_project.asgi.application"

DATABASES = {"default": dj_database_url.config(default="sqlite:///db.sqlite3")}

AUTH_USER_MODEL = "accounts.CustomUser"

# Formularz logowania prosi o e-mail, a Django domyślnie sprawdza username.
# Zwykły ModelBackend zostaje na końcu, żeby logowanie nazwą użytkownika
# (i panel /admin/) działało tak jak dotąd.
AUTHENTICATION_BACKENDS = [
    "accounts.auth_backends.EmailOrUsernameBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "pl"
TIME_ZONE = "Europe/Warsaw"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
# Klucze Stripe w ustawieniach wspólnych, nie tylko produkcyjnych: inaczej
# każde odwołanie do płatności poza produkcją kończyło się AttributeError,
# bo settings w ogóle nie miało tych atrybutów.
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# Identyfikatory cen ze Stripe, po jednym na plan z accounts/plans.py.
# W zmiennych, a nie w kodzie, bo cennik dopracowuje się częściej niż logikę.
STRIPE_PRICE_IDS = {
    "start": os.getenv("STRIPE_PRICE_START", ""),
    "grow": os.getenv("STRIPE_PRICE_GROW", ""),
    "pro": os.getenv("STRIPE_PRICE_PRO", ""),
}

# Ceny roczne (rabat 20%) to w Stripe osobne pozycje cennika, nie modyfikator
# ceny miesięcznej — stąd druga mapa zamiast przeliczania w kodzie.
STRIPE_PRICE_IDS_ROCZNE = {
    "start": os.getenv("STRIPE_PRICE_START_ROCZNY", ""),
    "grow": os.getenv("STRIPE_PRICE_GROW_ROCZNY", ""),
    "pro": os.getenv("STRIPE_PRICE_PRO_ROCZNY", ""),
}

# Pakiet doliczany po wyczerpaniu limitu (1000 wiadomości za 39 zł)
STRIPE_PRICE_PAKIET = os.getenv("STRIPE_PRICE_PAKIET", "")

OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")

# Bot obsługi klienta ma odtwarzać wiedzę firmy, nie tworzyć. Domyślna temperatura
# 1.0 sprzyja uzupełnianiu luk własnymi domysłami — przy pustym kontekście model
# potrafił opisać profil firmy zgadnięty z jej nazwy.
OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.2"))
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

# Ile ostatnich wiadomości konwersacji trafia do modelu jako kontekst
CHAT_HISTORY_LIMIT = int(os.getenv("CHAT_HISTORY_LIMIT", "10"))

# Sufity kosztu pojedynczej wiadomości. Bez nich prompt rósł z wielkością
# regulaminu klienta, a odpowiedź nie miała żadnego ograniczenia długości —
# jedno pytanie potrafiło kosztować wielokrotnie więcej niż typowe.
# Wejście przycinamy sami (api/utils/tokens.py), wyjście ogranicza model.
OPENAI_MAX_INPUT_TOKENS = int(os.getenv("OPENAI_MAX_INPUT_TOKENS", "6000"))
OPENAI_MAX_OUTPUT_TOKENS = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "600"))

# Najdłuższe sensowne pytanie odwiedzającego. Powyżej tego to albo wklejony
# dokument, albo próba nabicia nam kosztu na tokenach wejściowych.
MAX_WIADOMOSC_ZNAKOW = int(os.getenv("MAX_WIADOMOSC_ZNAKOW", "2000"))

# Ile serwerów pośredniczących stoi przed aplikacją i dopisuje się do
# X-Forwarded-For. Na Renderze ruch idzie przez Cloudflare i load balancer,
# więc 2; lokalnie 0. Wartość jest krytyczna: przy 0 za proxy wszyscy
# odwiedzający wyglądają jak jeden adres, a limit per IP zablokowałby wszystkich
# naraz. Ostrzega o tym django-check (accounts/checks.py).
TRUSTED_PROXY_DEPTH = int(os.getenv("TRUSTED_PROXY_DEPTH", "0"))

# Limit zapytań pojedynczego odwiedzającego. Chroni przed jednym natrętnym
# rozmówcą, który sam wyczerpałby miesięczny pakiet klienta.
LIMIT_ODWIEDZAJACEGO = os.getenv("LIMIT_ODWIEDZAJACEGO", "20/hour")

# Statystyki panelu nie muszą przeliczać całej historii przy każdym odświeżeniu.
# Krótki cache zachowuje praktycznie bieżące dane, a odciąża bazę i przyspiesza UI.
ANALYTICS_CACHE_SECONDS = int(os.getenv("ANALYTICS_CACHE_SECONDS", "15"))

# Próg odległości L2 dla wyszukiwania fragmentów — powyżej uznajemy, że dokument
# nie odpowiada na pytanie. Bez tego zawsze zwracane są "jakieś" fragmenty.
RAG_MAX_DISTANCE = float(os.getenv("RAG_MAX_DISTANCE", "1.15"))

# Minimalne podobieństwo pytania do wpisu FAQ (rapidfuzz, 0-100), by uznać trafienie
FAQ_MATCH_THRESHOLD = int(os.getenv("FAQ_MATCH_THRESHOLD", "65"))

# ─── Poczta wychodząca ───
#
# Wszystko ze zmiennych środowiskowych, bo dostawca poczty się zmienia,
# a zmiana dostawcy nie powinna wymagać wdrożenia kodu. Wartości domyślne
# wskazują Resend — dostawcę transakcyjnego, nie zwykłą skrzynkę.
#
# Poprzednio adres serwera był wpisany na sztywno na skrzynkę Hostingera.
# Gdy ta wygasła, powiadomienia o zapytaniach przestały wychodzić i jedynym
# sposobem naprawy była zmiana w kodzie.
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.resend.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "465"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")

# Django odmawia startu, gdy oba są włączone naraz. Wyliczamy jedno z portu,
# żeby nie dało się ustawić sprzecznej pary przez pomyłkę w zmiennych.
EMAIL_USE_SSL = EMAIL_PORT in (465, 2465)
EMAIL_USE_TLS = not EMAIL_USE_SSL

# NADAWCA TO OSOBNA RZECZ NIŻ LOGIN SMTP i tu leżała pułapka. U Hostingera
# jedno równało się drugiemu, więc kod brał adres z loginu. U dostawców
# transakcyjnych login jest techniczny — w Resendzie to dosłownie "resend",
# a hasłem jest klucz API. Nadawcą musi być zweryfikowany adres w Twojej
# domenie, inaczej wysyłka zostaje odrzucona.
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL") or EMAIL_HOST_USER

EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "30"))

# Sprawdzenie poprawności tych ustawień siedzi w ChatConfig.ready()
# (chat/kontrola_poczty.py). Było tutaj, ale pytało wyłącznie o OBECNOŚĆ
# zmiennych — a obie awarie, które realnie wystąpiły, były wartościami
# obecnymi i błędnymi: "stmp.resend.com" oraz nadawca z podkreślnikiem
# w domenie. Walidacja kształtu potrzebuje załadowanego Django, więc nie
# mieści się w module ustawień.
