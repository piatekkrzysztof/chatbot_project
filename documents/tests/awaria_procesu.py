"""Proces pomocniczy testu A04; dopuszcza wyłącznie lokalną bazę pytest."""

import json
import os
import socket
import sys
import time
from pathlib import Path


def main():
    config = json.load(sys.stdin)
    db = config["database"]
    if db["HOST"] not in ("localhost", "127.0.0.1", "::1") or not db["NAME"].startswith(
        "test_saas_restore_"
    ):
        raise RuntimeError("Próba wymaga lokalnej bazy test_saas_restore_*.")
    os.environ.update(
        PYTHON_DOTENV_DISABLED="1",
        DJANGO_SETTINGS_MODULE="chatbot_project.settings.dev",
        DJANGO_SECRET_KEY="synthetic-process-drill-key",
        OPENAI_API_KEY="not-used-local-drill",
        DEV_DB_NAME=db["NAME"],
        DEV_DB_HOST=db["HOST"],
        DEV_DB_PORT=str(db["PORT"]),
        DEV_DB_USER=db["USER"],
        DEV_DB_PASSWORD=db["PASSWORD"],
        REDIS_URL=config.get("broker", "memory://"),
    )
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_resolve = socket.getaddrinfo

    def check(address):
        if not isinstance(address, tuple) or address[0] not in ("localhost", "127.0.0.1", "::1"):
            raise RuntimeError("Próba blokuje połączenia zewnętrzne.")

    def connect(sock, address):
        check(address)
        return original_connect(sock, address)

    def connect_ex(sock, address):
        check(address)
        return original_connect_ex(sock, address)

    def resolve(host, port, *args, **kwargs):
        check((host, port))
        return original_resolve(host, port, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = resolve

    import django
    from django.conf import settings

    settings.STORAGES = config["storages"]
    settings.EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"
    settings.ALLOW_LEGACY_DOCUMENT_READS = False
    settings.CELERY_TASK_ALWAYS_EAGER = False
    django.setup()

    from django.core.files.storage import storages

    from chatbot_project import pliki
    from documents.models import Document
    from documents.usuwanie_plikow import wykonaj_usuniecie

    def wait_for_kill(*args):
        Path(config["marker"]).write_text("ready", encoding="utf-8")
        # Awaria testu nie może pozostawić nieskończonego procesu pomocniczego.
        time.sleep(45)
        raise RuntimeError("Proces testu nie został zakończony przez rodzica.")

    phase = config["phase"]
    if phase in ("callback", "broker"):
        if phase == "callback":
            pliki._obudz = wait_for_kill
        Document.objects.get(pk=config["pk"]).delete()
    else:
        storage = storages["private_documents"]
        original_delete = storage.delete

        def delete(name):
            if phase == "after_delete":
                original_delete(name)
            wait_for_kill()

        storage.delete = delete
        wykonaj_usuniecie(config["pk"])


if __name__ == "__main__":
    main()
