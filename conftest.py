import pytest
from dotenv import load_dotenv
from django.db import connection

# Załaduj plik .env.test przed testami
load_dotenv(".env.test")


# Dodaj rozszerzenie pgvector do bazy testowej
@pytest.fixture(scope="session", autouse=True)
def ensure_pgvector_installed(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
