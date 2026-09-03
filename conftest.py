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

# UWAGA przy odtwarzaniu warunków CI na własnej maszynie.
#
# Ustawienia ładują dotenv z KATALOGU PAKIETU, nie z korzenia repozytorium:
# `chatbot_project/.env`, a nie `./.env` (patrz settings/base.py, load_dotenv).
# Odsunięcie pliku z korzenia nie zmienia więc niczego - testy dalej widzą
# pełną konfigurację produkcyjną, łącznie z żywym kluczem Stripe.
#
# Kosztowało to dwa fałszywe „sprawdzone bez .env": raz przy alertach
# (accounts/tests/test_czuwanie.py), raz przy kartotece Stripe. W obu wypadkach
# CI znajdowało błąd, którego lokalna weryfikacja nie mogła zobaczyć.
#
# Poprawnie:
#     mv chatbot_project/.env chatbot_project/.env.bak
#     pytest -q
#     mv chatbot_project/.env.bak chatbot_project/.env
#
# Najlepiej jednak nie polegać na tym w ogóle: test, którego wynik zależy od
# pliku spoza repozytorium, nie mierzy kodu. Ustawiaj wymagane wartości wprost,
# fixture'ą `settings`.


@pytest.fixture(autouse=True)
def zadne_polaczenie_ze_stripe(monkeypatch):
    """
    Żaden test nie rozmawia z prawdziwym Stripe'em.

    Powód pierwszy, oczywisty: pakiet testów na maszynie z żywym kluczem
    w .env zakładałby prawdziwe kartoteki klientów i wystawiał prawdziwe
    sesje płatności. Narzędzie do sprawdzania kodu nie ma prawa ruszać
    cudzych pieniędzy.

    Powód drugi, mniej oczywisty i groźniejszy: kod płatności ma drogi
    awaryjne. Niepodstawione wywołanie bez klucza kończy się wyjątkiem, który
    te drogi łapią - więc test przechodzi, sprawdzając ścieżkę zapasową
    zamiast tej, o którą go pytano. Wynik wygląda wtedy na zielony i nie
    znaczy nic.

    Tutaj takie wywołanie kończy się głośnym błędem z nazwą brakującej atrapy,
    zamiast po cichu wpadać w gałąź awaryjną.
    """
    from stripe._api_requestor import _APIRequestor

    def zablokuj(*args, **kwargs):
        raise AssertionError(
            "Test probuje polaczyc sie z API Stripe. Podstaw konkretne "
            "wywolanie (np. stripe.Customer.create albo "
            "stripe.checkout.Session.create) zamiast pozwalac mu wyjsc "
            "na zewnatrz - inaczej sprawdzasz droge awaryjna, nie ta wlasciwa."
        )

    monkeypatch.setattr(_APIRequestor, "request", zablokuj)
    monkeypatch.setattr(_APIRequestor, "request_stream", zablokuj)


@pytest.fixture(autouse=True)
def zadania_w_miejscu(settings):
    """
    Zadania Celery wykonują się w procesie testu, zawsze.

    settings/dev.py włącza tryb inline tylko wtedy, gdy nikt nie wskazał
    brokera (`CELERY_TASK_ALWAYS_EAGER = not os.getenv("REDIS_URL")`) — bo
    inaczej stos z docker-compose byłby wewnętrznie sprzeczny: stoi w nim
    worker, a wszystko i tak wykonywałoby się w procesie web.

    Dla testów to zły domyślny stan. Uruchomione tam, gdzie REDIS_URL istnieje
    — czyli w kontenerze z docker-compose, dokładnie tak, jak opisuje README —
    zlecały zadania do prawdziwej kolejki i kończyły się, zanim ktokolwiek je
    wykonał. Padało pięć testów powiadomień i wektorów, i to nie dlatego, że
    kod jest zły, tylko dlatego, że nikt nie odebrał zadania.

    Test ma sprawdzać logikę zadania, nie to, czy w środowisku stoi broker.
    """
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True


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
    return Tenant.objects.create(name="TestTenant", owner_email="test@example.com")


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
    monkeypatch.setattr(
        "documents.tasks.generate_embeddings_for_document.delay", lambda *a, **kw: None
    )


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
def zablokuj_prawdziwe_openai(monkeypatch, request):
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
    # Furtka dla testów, które celowo sięgają po samą fabrykę — na przykład po
    # to, żeby sprawdzić, czy bierze klucz klienta, a nie globalny. Fabryka
    # tylko konstruuje obiekt, nie dzwoni nigdzie, więc taki test jest
    # bezpieczny. Marker robi z tego decyzję widoczną w kodzie testu, zamiast
    # cichego wyjątku od reguły.
    if request.node.get_closest_marker("wolno_uzyc_klienta_openai"):
        return

    def wybuchnij(*args, **kwargs):
        raise NiezamockowaneWywolanieOpenAI(
            "Test sięga po prawdziwe API OpenAI. Zamockuj "
            "api.utils.chat_engine.get_openai_response albo klienta, "
            "z którego korzysta testowany kod."
        )

    # raising=True jest tu istotne. Wcześniej stało tu raising=False, więc gdy
    # embedding_generator przestał mieć `client` (dostał fabrykę get_client),
    # monkeypatch nie zaprotestował — po cichu STWORZYŁ atrybut, którego nikt
    # nie używa. Strażnik pilnował wtedy martwej nazwy, a
    # test_generate_embeddings_for_document_creates_chunks mockował ją i wołał
    # prawdziwe API OpenAI: przechodził lokalnie (bo lokalnie jest klucz,
    # i płaciliśmy za każdy przebieg) i wywracał CI, gdzie klucza nie ma.
    #
    # Z raising=True zmiana nazwy w kodzie produkcyjnym wywali testy od razu,
    # zamiast po cichu wyłączyć zabezpieczenie.
    for sciezka in (
        "api.utils.chat_engine.get_client",
        "documents.utils.embedding_generator.get_client",
        "rag.engine.client",
    ):
        modul, atrybut = sciezka.rsplit(".", 1)
        monkeypatch.setattr(f"{modul}.{atrybut}", wybuchnij, raising=True)
