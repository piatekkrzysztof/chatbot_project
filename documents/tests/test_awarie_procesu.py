"""Rzeczywiste przerwanie procesu, odmowa TCP i błędy HTTP magazynu A04."""

import json
import os
import socket
import subprocess
import sys
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from celery.contrib.testing.worker import start_worker
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.db import connection
from django.utils import timezone

from chatbot_project.celery import app
from documents.models import Document, UsunieciePliku
from documents.usuwanie_plikow import cel_magazynu, wykonaj_usuniecie

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def local_files(settings, tmp_path):
    settings.STORAGES = {
        alias: {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(tmp_path / alias)},
        }
        for alias in ("default", "private_documents")
    }
    settings.ALLOW_LEGACY_DOCUMENT_READS = False
    return settings.STORAGES


def wait_until(check, timeout=25):
    end = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < end, "Przekroczono czas oczekiwania próby"
        time.sleep(0.05)


def child(config):
    # Nie dziedziczymy środowiska aplikacji ani plików .env.
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "LANG"}
    }
    config["database"] = {
        key: connection.settings_dict[key] for key in ("NAME", "HOST", "PORT", "USER", "PASSWORD")
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "documents.tests.awaria_procesu"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    process.stdin.write(json.dumps(config))
    process.stdin.close()
    return process


def recover_with_worker(job):
    old_broker, old_eager = app.conf.broker_url, app.conf.task_always_eager
    app.conf.update(CELERY_BROKER_URL="memory://", CELERY_TASK_ALWAYS_EAGER=False)
    try:
        with start_worker(
            app,
            pool="solo",
            concurrency=1,
            perform_ping_check=False,
            queues=["a04-recovery"],
            shutdown_timeout=15,
        ):
            with app.connection("memory://") as broker:
                app.send_task(
                    "documents.usuwanie_plikow.usun_oczekujace_pliki",
                    connection=broker,
                    queue="a04-recovery",
                    ignore_result=True,
                )
            wait_until(lambda: UsunieciePliku.objects.filter(pk=job.pk, stan="gotowe").exists())
    finally:
        app.conf.update(CELERY_BROKER_URL=old_broker, CELERY_TASK_ALWAYS_EAGER=old_eager)


@pytest.mark.parametrize("phase", ["callback", "before_delete", "after_delete"])
def test_killed_process_recovers_committed_intent(
    tenant, local_files, tmp_path, monkeypatch, phase
):
    monkeypatch.setattr("chatbot_project.pliki._obudz", lambda *args: None)
    doc = Document.objects.create(tenant=tenant, name="synthetic", processed=True)
    doc.file.save("process.txt", ContentFile(b"synthetic-process-data"))
    name, pk = doc.file.name, doc.pk
    if phase != "callback":
        doc.delete()
        pk = UsunieciePliku.objects.get().pk
    marker = tmp_path / "ready"
    process = child({"phase": phase, "pk": pk, "marker": str(marker), "storages": local_files})
    try:

        def ready():
            assert process.poll() is None, process.stderr.read()
            return marker.exists()

        wait_until(ready)
        process.kill()  # SIGKILL na Linux; TerminateProcess na Windows, bez finally dziecka.
        assert process.wait(timeout=10) != 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        process.stdout.close()
        process.stderr.close()
    assert not Document.objects.exists()
    job = UsunieciePliku.objects.get()
    assert storages["private_documents"].exists(name) == (phase != "after_delete")
    if phase != "callback":
        assert job.stan == "praca" and job.proby == 1
        token = job.token
        assert not wykonaj_usuniecie(job.pk)  # Dzierżawa wyklucza przedwczesne przejęcie.
        UsunieciePliku.objects.filter(pk=job.pk).update(
            dzierzawa_do=timezone.now() - timedelta(seconds=1)
        )  # Przyspieszenie zegara dzierżawy; nie czekamy 10 minut w CI.
    else:
        assert job.stan == "oczekuje" and job.proby == 0
    recover_with_worker(job)
    job.refresh_from_db()
    assert job.proby == (1 if phase == "callback" else 2)
    if phase != "callback":
        assert job.token != token
    assert not storages["private_documents"].exists(name)


def test_real_connection_refusal_keeps_intent_and_worker_recovers(tenant, local_files):
    doc = Document.objects.create(tenant=tenant, name="synthetic", processed=True)
    doc.file.save("broker.txt", ContentFile(b"synthetic-broker-data"))
    # Zarezerwowany port bez listen: prawdziwe ECONNREFUSED, bez obcego brokera.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
        process = child(
            {
                "phase": "broker",
                "pk": doc.pk,
                "storages": local_files,
                "broker": f"redis://127.0.0.1:{port}/0",
            }
        )
        try:
            assert process.wait(timeout=25) == 0, process.stderr.read()
            assert "id=" in process.stderr.read()  # Produkcyjny log ścieżki nieudanego publish.
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            process.stdout.close()
            process.stderr.close()
    job = UsunieciePliku.objects.get()
    assert not Document.objects.exists()
    assert job.stan == "oczekuje" and job.proby == 0
    assert storages["private_documents"].exists(job.nazwa)
    recover_with_worker(job)
    assert not storages["private_documents"].exists(job.nazwa)


def test_s3_http_failure_retry_and_recovery(settings):
    state = {"fail": True, "calls": []}

    class Handler(BaseHTTPRequestHandler):
        def do_DELETE(self):
            state["calls"].append(self.path)
            body = b"<Error><Code>ServiceUnavailable</Code></Error>" if state["fail"] else b""
            self.send_response(503 if state["fail"] else 204)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings.STORAGES = {
            "private_documents": {
                "BACKEND": "storages.backends.s3.S3Storage",
                "OPTIONS": {
                    "endpoint_url": f"http://127.0.0.1:{server.server_port}",
                    "bucket_name": "synthetic-a04",
                    "region_name": "auto",
                    "access_key": "synthetic",
                    "secret_key": "synthetic",
                    "addressing_style": "path",
                },
            }
        }
        job = UsunieciePliku.objects.create(
            magazyn="private_documents",
            cel=cel_magazynu("private_documents"),
            nazwa="synthetic.txt",
        )
        assert wykonaj_usuniecie(job.pk)
        job.refresh_from_db()
        assert job.stan == "oczekuje" and job.blad == "blad_magazynu" and job.proby == 1
        assert len(state["calls"]) == 2  # Pierwsze DELETE + jeden retry SDK.
        assert not wykonaj_usuniecie(job.pk)
        assert len(state["calls"]) == 2
        state["fail"] = False
        UsunieciePliku.objects.filter(pk=job.pk).update(ponow_at=timezone.now())
        assert wykonaj_usuniecie(job.pk)
        job.refresh_from_db()
        assert job.stan == "gotowe" and job.proby == 2
        assert state["calls"] == ["/synthetic-a04/synthetic.txt"] * 3
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
