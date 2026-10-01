from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from accounts.models import PrzebiegMonitora
from accounts.tasks_monitoring import potwierdz_przebieg
from chatbot_project.celery import app
from chatbot_project.monitoring_zadan import NAGLOWEK, PROG_SEKUND, ZADANIE

pytestmark = pytest.mark.django_db


def wykonaj(stamp, **request):
    potwierdz_przebieg.push_request(
        headers={NAGLOWEK: stamp}, called_directly=False, is_eager=False, **request
    )
    try:
        potwierdz_przebieg.run()
    finally:
        potwierdz_przebieg.pop_request()


def health(client):
    with patch("chatbot_project.zdrowie._broker_odpowiada", return_value=True):
        return client.get("/health/")


def test_brak_pierwszej_proby_jest_ograniczeniem_bez_restartu_web(client):
    response = health(client)
    assert response.status_code == 200
    assert response.json()["stan"] == "ograniczony"
    assert response.json()["zadania"] is False
    assert response.json()["status"] == "ok"
    assert "no-store" in response["Cache-Control"]


def test_swieza_proba_przeterminowanie_i_odzyskanie(client):
    teraz = timezone.now()
    with patch("django.utils.timezone.now", return_value=teraz):
        wykonaj(teraz.timestamp())
        assert health(client).json()["stan"] == "ok"
    # Bez Beat albo bez workera nie ma kolejnych zapisów. Broker nadal działa.
    pozniej = teraz + timedelta(seconds=PROG_SEKUND + 1)
    with patch("django.utils.timezone.now", return_value=pozniej):
        assert health(client).json()["zadania"] is False
        assert health(client).json()["stan"] == "ograniczony"
        wykonaj(pozniej.timestamp())
        assert health(client).json()["stan"] == "ok"
    assert PrzebiegMonitora.objects.count() == 1


def test_wiek_od_publikacji_nie_od_wykonania(client):
    teraz = timezone.now()
    with patch("django.utils.timezone.now", return_value=teraz):
        wykonaj((teraz - timedelta(seconds=170)).timestamp())
        assert health(client).json()["zadania"] is True
    with patch("django.utils.timezone.now", return_value=teraz + timedelta(seconds=11)):
        assert health(client).json()["zadania"] is False


@pytest.mark.parametrize("stamp", [None, True, "123", float("nan"), float("inf"), -1])
def test_bledny_naglowek_nie_potwierdza_zdrowia(stamp):
    wykonaj(stamp)
    assert not PrzebiegMonitora.objects.exists()


@pytest.mark.parametrize("offset", [-181, 1])
def test_stara_lub_przyszla_wiadomosc_nie_potwierdza_zdrowia(offset):
    teraz = timezone.now()
    with patch("django.utils.timezone.now", return_value=teraz):
        wykonaj((teraz + timedelta(seconds=offset)).timestamp())
    assert not PrzebiegMonitora.objects.exists()


def test_starsza_proba_nie_nadpisuje_nowszej():
    teraz = timezone.now()
    wykonaj(teraz.timestamp())
    wykonaj((teraz - timedelta(seconds=50)).timestamp())
    assert PrzebiegMonitora.objects.get(pk=1).wyslano_at == teraz


def test_lokalne_wywolanie_nie_przechodzi_przez_kolejke():
    potwierdz_przebieg()
    potwierdz_przebieg.apply(headers={NAGLOWEK: timezone.now().timestamp()})
    assert not PrzebiegMonitora.objects.exists()


def test_blad_odczytu_nie_ujawnia_szczegolow_i_nie_daje_ok(client):
    with patch(
        "accounts.models.PrzebiegMonitora.objects.filter",
        side_effect=RuntimeError("secret-db-host"),
    ):
        response = health(client)
    assert response.status_code == 200
    assert response.json()["zadania"] is False
    assert b"secret-db-host" not in response.content


def test_sygnal_publikacji_jest_podlaczony_do_rzeczywistej_wysylki():
    # Pamięciowy transport Kombu: sprawdzamy serializowane nagłówki, nie mock sygnału.
    with app.connection("memory://") as conn:
        with conn.SimpleQueue("monitoring-test") as queue:
            queue.clear()
            with patch("chatbot_project.monitoring_zadan.time.time", return_value=123456.0):
                app.send_task(ZADANIE, connection=conn, queue="monitoring-test", ignore_result=True)
            message = queue.get(block=False)
            assert message.headers[NAGLOWEK] == 123456.0
            message.ack()


def test_harmonogram_ma_krotka_waznosc_i_zarejestrowane_zadanie():
    app.autodiscover_tasks(force=True)
    entry = app.conf.beat_schedule["monitoring-workera-co-minute"]
    assert entry["task"] == ZADANIE
    assert entry["schedule"] == 60.0
    assert entry["options"]["expires"] == 60
    assert ZADANIE in app.tasks


@pytest.mark.django_db(transaction=True)
def test_beat_broker_worker_zapisuja_slad_w_bazie(client):
    import time

    from celery.beat import ScheduleEntry, Scheduler
    from celery.contrib.testing.worker import start_worker

    old_broker = app.conf.broker_url
    old_eager = app.conf.task_always_eager
    app.conf.update(CELERY_BROKER_URL="memory://")
    app.conf.update(CELERY_TASK_ALWAYS_EAGER=False)
    try:
        with start_worker(
            app,
            pool="solo",
            concurrency=1,
            perform_ping_check=False,
            queues=["monitoring-e2e"],
            shutdown_timeout=15,
        ):
            entry = ScheduleEntry(
                name="monitoring-e2e",
                task=ZADANIE,
                schedule=60.0,
                options={"queue": "monitoring-e2e", "expires": 60},
                app=app,
            )
            scheduler = Scheduler(app=app, lazy=True)
            try:
                with app.connection("memory://") as conn:
                    scheduler.apply_async(entry, producer=app.amqp.Producer(conn))
                deadline = time.monotonic() + 10
                while not PrzebiegMonitora.objects.filter(pk=1).exists():
                    assert time.monotonic() < deadline, "Worker nie potwierdził próby Beat"
                    time.sleep(0.1)
                assert health(client).json()["zadania"] is True
            finally:
                scheduler.close()
    finally:
        app.conf.update(CELERY_BROKER_URL=old_broker)
        app.conf.update(CELERY_TASK_ALWAYS_EAGER=old_eager)
