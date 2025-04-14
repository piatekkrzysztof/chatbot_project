import os
import pytest
import psycopg2
from dotenv import load_dotenv
from django.conf import settings
from django.core.management import call_command

# Wczytujemy zmienne środowiskowe z .env.test
load_dotenv(".env.test")


@pytest.fixture(scope="session")
def django_db_setup():
    # Nadpisujemy konfigurację bazy danych tylko na czas testów
    settings.DATABASES["default"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["PGDATABASE"],
        "USER": os.environ["PGUSER"],
        "PASSWORD": os.environ["PGPASSWORD"],
        "HOST": os.environ["PGHOST"],
        "PORT": os.environ.get("PGPORT", "5432"),
        "ATOMIC_REQUESTS": True,
    }


@pytest.fixture(scope="session", autouse=True)
def ensure_pgvector_installed(django_db_setup):
    """
    Tworzy rozszerzenie pgvector w testowej bazie, jeśli nie istnieje.
    """
    conn = psycopg2.connect(
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        host=os.environ["PGHOST"],
        port=os.environ.get("PGPORT", "5432"),
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    conn.close()


@pytest.fixture(scope="session", autouse=True)
def run_migrations(django_db_setup, django_db_blocker):
    """
    Wykonuje migracje po przygotowaniu połączenia i instalacji rozszerzenia.
    """
    with django_db_blocker.unblock():
        call_command("migrate")
