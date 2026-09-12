"""A complete, encrypted application snapshot including referenced file bytes."""

import tempfile
import uuid
from pathlib import Path

from django.conf import settings
from django.core.checks import Tags
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.backups import private_backup_storage
from accounts.full_backups import create_bundle, verify_bundle


class Command(BaseCommand):
    help = "Pełna kopia bazy i wskazanych plików; wymaga wstrzymania zapisów źródła."
    requires_system_checks = [Tags.models]

    def add_arguments(self, parser):
        parser.add_argument("--source-quiesced", action="store_true")
        parser.add_argument("--output")
        parser.add_argument("--to-storage", action="store_true")

    def handle(self, *args, **options):
        if not options["output"] and not options["to_storage"]:
            raise CommandError("Podaj --output albo --to-storage.")
        if not options["source_quiesced"]:
            raise CommandError("Najpierw wstrzymaj zapisy źródła; następnie --source-quiesced.")
        storage = private_backup_storage() if options["to_storage"] else None
        # Temporary storage contains ciphertext only; no plaintext fixture on source disk.
        with tempfile.TemporaryFile(mode="w+b") as encrypted:
            try:
                manifest = create_bundle(encrypted, source_quiesced=True)
                verify_bundle(encrypted)
            except CommandError:
                raise
            except Exception:
                raise CommandError(
                    "Nie udało się utworzyć pełnej kopii; zachowaj poprzednie kopie."
                ) from None
            if options["output"]:
                target = Path(options["output"]).resolve()
                if target.is_relative_to(Path(settings.MEDIA_ROOT).resolve()):
                    raise CommandError("Kopii nie wolno zapisywać w publicznym MEDIA_ROOT.")
                import os

                descriptor = os.open(
                    target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600
                )
                try:
                    encrypted.seek(0)
                    with os.fdopen(descriptor, "wb") as output:
                        while block := encrypted.read(1024 * 1024):
                            output.write(block)
                except BaseException:
                    target.unlink(missing_ok=True)
                    raise
            if storage is not None:
                name = f"full-backups/full-{timezone.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex}.saas"
                try:
                    encrypted.seek(0)
                    saved = storage.save(name, File(encrypted))
                    # S3 backends may spool downloads to disk: allow ciphertext only.
                    with storage.open(saved, "rb") as returned:
                        actual = verify_bundle(returned)
                    if actual != manifest:
                        raise CommandError("Zdalny manifest różni się od wysłanego.")
                except CommandError:
                    raise
                except Exception:
                    raise CommandError(
                        "Nie można zapisać i zweryfikować pełnej kopii w prywatnym magazynie."
                    ) from None
                self.stdout.write(f"Wysłano i zweryfikowano pełną kopię: {saved}")
        self.stdout.write(
            f"Pełna kopia zweryfikowana; pliki: {len(manifest['files'])}; "
            f"bajty: {manifest['total_bytes']}."
        )
