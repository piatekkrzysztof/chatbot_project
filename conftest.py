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


@pytest.fixture(autouse=True)
def wyczysc_liczniki_limitow():
    """
    Zeruje liczniki throttlingu przed każdym testem.

    Throttling DRF trzyma je w cache wspólnym dla całej sesji testowej, a klucz
    to identyfikator firmy — te same w kolejnych testach. Bez czyszczenia test
    startował z budżetem zużytym przez poprzedni i wywracał się zależnie od
    kolejności uruchomienia, co wygląda na błąd losowy.
    """
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


class NiezamockowaneWywolanieOpenAI(AssertionError):
    """Test próbuje wywołać prawdziwe API OpenAI."""


@pytest.fixture(autouse=True)
def zablokuj_prawdziwe_openai(monkeypatch):
    """
    Zamienia niezamockowane wywołanie OpenAI w jawny błąd testu.

    Test limitu wiadomości wykonywał tyle realnych, płatnych wywołań, ile
    wynosił limit — i nikt tego nie zauważył, bo przechodził. Skutek nie był
    tylko kosztowy: pętla trwała ponad minutę, a throttling liczy żądania
    w oknie sześćdziesięciu sekund, więc najstarsze zdążały z niego wypaść
    i limit nie zapinał się na końcu. Test wywracał się zależnie od kolejności
    uruchomienia, co wygląda na błąd losowy i zjada wieczór.

    Testy, które mockują get_openai_response, w ogóle tu nie docierają.
    """
    def wybuchnij(*args, **kwargs):
        raise NiezamockowaneWywolanieOpenAI(
            "Test sięga po prawdziwe API OpenAI. Zamockuj "
            "api.utils.chat_engine.get_openai_response albo klienta, "
            "z którego korzysta testowany kod."
        )

    for sciezka in (
        "api.utils.chat_engine.get_client",
        "documents.utils.embedding_generator.client",
        "rag.engine.client",
    ):
        modul, atrybut = sciezka.rsplit(".", 1)
        monkeypatch.setattr(f"{modul}.{atrybut}", wybuchnij, raising=False)
