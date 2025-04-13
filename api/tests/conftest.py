import pytest
import os
from dotenv import load_dotenv
from django.db import connection

# Załaduj zmienne środowiskowe .env.dev
load_dotenv(dotenv_path=".env.dev")
print(">>> PG HOST:", os.environ.get("POSTGRES_HOST"))

@pytest.fixture(scope="session", autouse=True)
def ensure_pgvector_installed(django_db_setup, django_db_blocker):
    """
    Fixture, który uruchamia się raz przed testami
    i instaluje rozszerzenie vector w testowej bazie.
    """
    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")