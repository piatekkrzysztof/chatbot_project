import io
import uuid
from datetime import date, timedelta

import pytest
from dotenv import load_dotenv
from django.core.files.uploadedfile import SimpleUploadedFile
from reportlab.pdfgen import canvas
from rest_framework.test import APIClient

from accounts.models import Tenant, Subscription, CustomUser
from chat.models import Conversation

# Zmienne środowiskowe na czas testów (m.in. klucze API)
load_dotenv(".env.test", override=True)



@pytest.fixture
def valid_pdf_file():
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer)
    p.drawString(100, 750, "Test PDF content")
    p.showPage()
    p.save()
    buffer.seek(0)
    return SimpleUploadedFile("test.pdf", buffer.read(), content_type="application/pdf")


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(
        name="TestTenant",
        owner_email="test@example.com"
    )

@pytest.fixture
def conversation(tenant):
    return Conversation.objects.create(
        tenant=tenant,
        user_identifier="test-user",
    )

@pytest.fixture
def subscribtion(db, tenant):
    return Subscription.objects.create(
        tenant=tenant,
        is_active=True,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=30),
    )


@pytest.fixture
def user(db, tenant):
    return CustomUser.objects.create_user(
        username="x", email="x@x.com", password="secret", tenant=tenant
    )


@pytest.fixture
def api_client():
    return APIClient()


# @pytest.fixture
# def api_client(tenant):
#     """
#     Klient DRF z domyślnie ustawionym nagłówkiem X-API-KEY.
#     """
#     client = APIClient()
#     client.credentials(HTTP_X_API_KEY=tenant.api_key)
#     return client


@pytest.fixture(autouse=True)
def mock_celery_tasks(monkeypatch):
    monkeypatch.setattr("documents.tasks.embed_document_task.delay", lambda *a, **kw: None)
    monkeypatch.setattr("documents.tasks.extract_text_from_document.delay", lambda *a, **kw: None)
    monkeypatch.setattr("documents.tasks.generate_embeddings_for_document.delay", lambda *a, **kw: None)


# Baza testowa jest tworzona i usuwana przez pytest-django (prefiks "test_"),
# odizolowana od bazy deweloperskiej. Wcześniej conftest podmieniał
# settings.DATABASES już po nawiązaniu połączenia przez Django — ustawienie się
# zmieniało, ale połączenie nadal wskazywało bazę z dev.py, więc testy pisały po
# danych deweloperskich. Rozszerzenie pgvector zakłada migracja
# documents/0005_enable_pgvector.
