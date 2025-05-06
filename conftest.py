import os
import pytest
import uuid
from rest_framework.test import APIClient
from accounts.models import Tenant
import psycopg2
from dotenv import load_dotenv
from django.conf import settings
from django.core.management import call_command

# Wczytujemy zmienne środowiskowe z .env.test
load_dotenv(".env.test")




@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Firma Testowa",
                                 api_key=str(uuid.uuid4()),
                                 owner_email="owner@example.com")


@pytest.fixture
def api_client(tenant):
    """
    Klient DRF z domyślnie ustawionym nagłówkiem X-API-KEY.
    """
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=tenant.api_key)
    return client


@pytest.fixture(autouse=True)
def mock_celery_tasks(monkeypatch):
    monkeypatch.setattr("documents.tasks.embed_document_task.delay", lambda *a, **kw: None)
    monkeypatch.setattr("documents.tasks.extract_text_from_document.delay", lambda *a, **kw: None)
    monkeypatch.setattr("documents.tasks.generate_embeddings_for_document.delay", lambda *a, **kw: None)


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
