"""Szyfrowana kopia danych aplikacji; zdalny zapis tylko do osobnego magazynu."""

import uuid
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.backups import (
    BackupBuffer,
    backup_cipher,
    encrypt_backup,
    validate_backup,
    write_new_file,
)
from chatbot_project.storage import PrivateS3Storage

POMIJANE = ["contenttypes", "auth.permission", "sessions", "admin.logentry"]


class Command(BaseCommand):
    help = "Szyfruje dane aplikacji. Odtworzenie: decrypt_backup, a następnie loaddata."

    def add_arguments(self, parser):
        parser.add_argument("--output", help="Nowy lokalny plik zaszyfrowanej kopii.")
        parser.add_argument(
            "--to-storage",
            action="store_true",
            help="Wyślij szyfrogram do private_backups; bez --output nie powstaje plik lokalny.",
        )

    def handle(self, *args, **options):
        backup_cipher()  # Walidacja przed odczytaniem danych i sekretów.
        storage = None
        if options["to_storage"]:
            storage = storages["private_backups"]
            if not isinstance(storage, PrivateS3Storage):
                raise CommandError(
                    "--to-storage wymaga skonfigurowanego prywatnego magazynu obiektowego."
                )

        with BackupBuffer() as buffer:
            call_command(
                "dumpdata",
                *[f"--exclude={label}" for label in POMIJANE],
                indent=2,
                stdout=buffer,
            )
            plaintext = buffer.getvalue().encode("utf-8")
        count = validate_backup(plaintext)
        ciphertext = encrypt_backup(plaintext)
        name = f"kopia-{timezone.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex}.json.fernet"
        output = options.get("output")
        if not options["to_storage"] and not output:
            output = str(Path("backups") / name)
        if output:
            write_new_file(output, ciphertext)
            self.stdout.write("Zapisano zaszyfrowaną kopię lokalną.")
        if storage is not None:
            saved = storage.save(f"backups/{name}", ContentFile(ciphertext))
            self.stdout.write(f"Wysłano zaszyfrowaną kopię: {saved}")
        self.stdout.write(f"Obiektów: {count}; rozmiar szyfrogramu: {len(ciphertext)} B.")
        self.stdout.write(
            "Odtworzenie: decrypt_backup <kopia> --output <nowy.json>, "
            "potem loaddata <nowy.json> w przygotowanej bazie."
        )
