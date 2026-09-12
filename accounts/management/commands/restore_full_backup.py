"""Guarded local drill, never an in-place production restore."""

import hashlib
import hmac
import os
import socket
import time
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.test.utils import override_settings
from psycopg2 import sql

from accounts.full_backups import backup_models, references, unpack_bundle, verify_bundle
from chatbot_project.wersja import WERSJA


def validate_target(manifest):
    config = connection.settings_dict
    if (
        os.getenv("RENDER")
        or os.getenv("RENDER_EXTERNAL_HOSTNAME")
        or connection.vendor != "postgresql"
        or config["HOST"] not in ("127.0.0.1", "localhost", "::1")
        or not config["NAME"].startswith(("saas_restore_", "test_saas_restore_"))
    ):
        raise CommandError("Próba wymaga lokalnej bazy saas_restore_* poza Renderem.")
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_setting('server_version_num')")
        name, version = cursor.fetchone()
    if name != config["NAME"] or int(version) // 10000 != int(manifest["postgres"].split(".")[0]):
        raise CommandError("Cel ma inną nazwę lub główną wersję PostgreSQL niż kopia.")
    expected = sorted([list(x) for x in MigrationRecorder(connection).applied_migrations()])
    if expected != manifest["migrations"] or manifest["version"] != WERSJA:
        raise CommandError("Wersja aplikacji i migracje celu muszą odpowiadać kopii.")
    proof = hmac.new(
        settings.SECRET_KEY.encode(), manifest["id"].encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(proof, manifest["django_key_proof"]):
        raise CommandError(
            "DJANGO_SECRET_KEY celu nie odpowiada kopii; MFA/sesje wymagają właściwego klucza."
        )
    if any(model._base_manager.exists() for model in backup_models()):
        raise CommandError(
            "Cel zawiera dane aplikacji; odtwarzanie wymaga pustej bazy po migracjach."
        )


class Command(BaseCommand):
    help = (
        "Odtwarza kopię tylko do pustej lokalnej bazy saas_restore_* i nowego prywatnego katalogu."
    )
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("source")
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        start = time.monotonic()
        original_connect = socket.socket.connect
        original_resolve = socket.getaddrinfo
        host = connection.settings_dict["HOST"]
        port = int(connection.settings_dict["PORT"] or 5432)

        def local_database_only(sock, address):
            if (
                isinstance(address, tuple)
                and address[0] in ("127.0.0.1", "localhost", "::1")
                and address[1] == port
                and host in ("127.0.0.1", "localhost", "::1")
            ):
                return original_connect(sock, address)
            raise CommandError("Połączenia zewnętrzne są zablokowane podczas odtwarzania.")

        def local_resolve(name, service, *args, **kwargs):
            if name not in ("localhost", "127.0.0.1", "::1") or int(service) != port:
                raise CommandError("Zewnętrzne DNS jest zablokowane podczas odtwarzania.")
            return original_resolve(name, service, *args, **kwargs)

        try:
            with open(options["source"], "rb") as stream:
                manifest = verify_bundle(stream)
                # Connect restrictions apply even to validation; never inspect a remote DB.
                with (
                    patch.object(socket, "getaddrinfo", local_resolve),
                    patch.object(socket.socket, "connect", local_database_only),
                    patch.object(
                        socket.socket,
                        "connect_ex",
                        side_effect=CommandError("Sieć zewnętrzna zablokowana."),
                    ),
                ):
                    validate_target(manifest)
                    root = Path(options["output"]).resolve()
                    if unpack_bundle(stream, root) != manifest:
                        raise CommandError("Kopia zmieniła się podczas odtwarzania.")
                    local_storages = {
                        **settings.STORAGES,
                        "default": {
                            "BACKEND": "django.core.files.storage.FileSystemStorage",
                            "OPTIONS": {"location": str(root / "public")},
                        },
                        "private_documents": {
                            "BACKEND": "django.core.files.storage.FileSystemStorage",
                            "OPTIONS": {"location": str(root / "private_documents")},
                        },
                        "private_backups": {
                            "BACKEND": "chatbot_project.storage.UnconfiguredPrivateStorage"
                        },
                    }
                    with override_settings(
                        STORAGES=local_storages,
                        EMAIL_BACKEND="django.core.mail.backends.dummy.EmailBackend",
                        CELERY_TASK_ALWAYS_EAGER=False,
                        CELERY_BROKER_URL="memory://",
                    ):
                        with transaction.atomic():
                            tables = sql.SQL(", ").join(
                                sql.Identifier(model._meta.db_table) for model in backup_models()
                            )
                            with connection.cursor() as cursor:
                                cursor.execute(
                                    sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE NOWAIT").format(
                                        tables
                                    )
                                )
                            # A writer could have arrived while the files were unpacked.
                            validate_target(manifest)
                            try:
                                call_command("loaddata", str(root / "database.json"), verbosity=0)
                            except Exception:
                                raise CommandError(
                                    "Import bazy nieudany; transakcja wycofana."
                                ) from None
                            counts = {
                                model._meta.label_lower: model._base_manager.count()
                                for model in backup_models()
                            }
                            if {key: count for key, count in counts.items() if count} != manifest[
                                "model_counts"
                            ]:
                                raise CommandError(
                                    "Liczba odtworzonych rekordów różni się od manifestu."
                                )

                            def refs(items):
                                return sorted(
                                    (
                                        item["storage"],
                                        item["name"],
                                        ref["model"],
                                        ref["field"],
                                        ref["pk"],
                                    )
                                    for item in items
                                    for ref in item["refs"]
                                )

                            if refs(references().values()) != refs(manifest["files"]):
                                raise CommandError(
                                    "Odtworzone powiązania plików różnią się od manifestu."
                                )
        except CommandError:
            raise
        except Exception:
            raise CommandError(
                "Próba odtwarzania nieudana. Nie uruchamiaj aplikacji z częściowego katalogu."
            ) from None
        self.stdout.write(
            f"Lokalne odtworzenie zakończone; pliki: {len(manifest['files'])}; "
            f"czas: {time.monotonic() - start:.2f} s. "
            "Nie uruchomiono procesów aplikacji ani workera."
        )
