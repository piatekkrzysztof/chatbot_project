from django.db import connection
from django.core.management.color import no_style
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
import pytest


@pytest.fixture(scope="session", autouse=True)
def enable_pgvector_extension(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")


def test_pgvector_column_supported(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            cursor.execute("CREATE TEMP TABLE test_vector (embedding vector(3));")
            cursor.execute("INSERT INTO test_vector (embedding) VALUES ('[1,2,3]');")
            cursor.execute("SELECT embedding FROM test_vector;")
            result = cursor.fetchone()
            assert result is not None
