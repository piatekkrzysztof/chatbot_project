import pytest
import os
from dotenv import load_dotenv
from django.conf import settings
from django.db import connection
from django.core.management import call_command

load_dotenv(".env.test")


@pytest.fixture(scope="session")
def django_db_setup():
    settings.DATABASES["default"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["PGDATABASE"],
        "USER": os.environ["PGUSER"],
        "PASSWORD": os.environ["PGPASSWORD"],
        "HOST": os.environ["PGHOST"],
        "PORT": os.environ["PGPORT"],
    }


@pytest.fixture(scope="session", autouse=True)
def setup_db_and_vector(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        call_command("migrate")
