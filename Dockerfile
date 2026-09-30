# Obraz aplikacji: serwer HTTP i worker Celery uruchamiają się z tego samego.
#
# Poprzednia wersja instalowała postgresql-server-dev-15 i osobno pgvector.
# Ani jedno, ani drugie nie było potrzebne: psycopg2-binary to gotowe koło
# (żadnej kompilacji), a pgvector siedzi w requirements.txt. Ten apt-get
# dokładał ~250 MB i ponad minutę do każdego budowania.
FROM python:3.11-slim AS base

# Obraz bazowy może jeszcze nie zawierać opublikowanych poprawek Debiana.
# CI A04 wykrył OpenSSL 3.5.7-1~deb13u2; poprawka jest w deb13u3.
# Aktualizujemy z podpisanych repozytoriów dystrybucji, bez wyłączania skanu.
# Przy nowej luce i trafieniu w cache przebudować z --pull --no-cache.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# PYTHONUNBUFFERED: bez tego logi Pythona wiszą w buforze i `docker compose logs`
#   pokazuje pustkę, dopóki proces nie zapisze 8 KB albo nie padnie.
# PYTHONDONTWRITEBYTECODE: katalog jest podmontowany z hosta, .pyc tylko
#   zaśmiecałyby drzewo źródeł.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Zależności osobną warstwą przed kodem: zmiana pliku .py nie unieważnia
# wtedy cache'u pip i przebudowa trwa sekundy zamiast minut.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# docker-compose używa tego etapu i podmontowuje kod z hosta.
FROM base AS development
COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
RUN useradd --create-home --uid 10001 aplikacja
USER aplikacja

# Ostatni etap jest domyślnym obrazem produkcyjnym. Nie dziedziczy narzędzi
# testowych, lokalnych danych ani plików środowiska z etapu development.
FROM base AS production
COPY manage.py ./
COPY accounts/ ./accounts/
COPY api/ ./api/
COPY chat/ ./chat/
COPY chatbot_project/ ./chatbot_project/
COPY documents/ ./documents/
COPY rag/ ./rag/

# Obraz runtime nie instaluje niczego, więc nie potrzebuje pip, setuptools ani
# wheel. Dopóki tu leżały, skan podatności zgłaszał je co przebieg - i były to
# zgłoszenia nie do naprawienia: setuptools wozi w `_vendor` własne kopie
# jaraco.context i wheel, a sprawdzone setuptools 80.9.0 wozi dokładnie te
# same podatne wersje co 79.0.1. Podbicie wersji nic nie dawało, bo poprawka
# musiałaby wyjść po stronie setuptools, nie naszej.
#
# Usunięcie ich naprawia przyczynę zamiast uciszać objaw i przy okazji zdejmuje
# z obrazu produkcyjnego kod, który potrafi rozpakowywać archiwa i instalować
# pakiety - a tego w działającej usłudze nie robi nic.
#
# Sprawdzone przed usunięciem: ani nasz kod, ani Django, celery i kombu nie
# importują `pkg_resources`. Sentry ma taki import wyłącznie jako gałąź dla
# Pythona starszego niż 3.8, za `try/except ImportError`.
RUN pip uninstall --yes setuptools wheel pip

# Procesy aplikacji działają jako zwykły użytkownik.
RUN useradd --create-home --uid 10001 aplikacja \
    && chown -R aplikacja:aplikacja /app
USER aplikacja

EXPOSE 8000

CMD ["gunicorn", "chatbot_project.wsgi:application", "--bind", "0.0.0.0:8000"]
