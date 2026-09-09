# Obraz aplikacji: serwer HTTP i worker Celery uruchamiają się z tego samego.
#
# Poprzednia wersja instalowała postgresql-server-dev-15 i osobno pgvector.
# Ani jedno, ani drugie nie było potrzebne: psycopg2-binary to gotowe koło
# (żadnej kompilacji), a pgvector siedzi w requirements.txt. Ten apt-get
# dokładał ~250 MB i ponad minutę do każdego budowania.
FROM python:3.11-slim AS base

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

# Procesy aplikacji działają jako zwykły użytkownik.
RUN useradd --create-home --uid 10001 aplikacja \
    && chown -R aplikacja:aplikacja /app
USER aplikacja

EXPOSE 8000

CMD ["gunicorn", "chatbot_project.wsgi:application", "--bind", "0.0.0.0:8000"]
