import json
import math

from django.core.management.base import BaseCommand, CommandError

from accounts.backups import private_backup_storage
from accounts.full_backups import verify_bundle


class Command(BaseCommand):
    help = "Sprawdza szyfrowanie, kompletność i wiek pełnej kopii; bez odtwarzania."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("source")
        parser.add_argument("--from-storage", action="store_true")
        parser.add_argument("--max-age-hours", type=float, default=30)

    def handle(self, *args, **options):
        age = options["max_age_hours"]
        if not math.isfinite(age) or not 0 < age <= 8760:
            raise CommandError("Nieprawidłowy maksymalny wiek kopii.")
        try:
            stream = (
                private_backup_storage().open(options["source"], "rb")
                if options["from_storage"]
                else open(options["source"], "rb")
            )
            with stream:
                manifest = verify_bundle(stream, max_age_hours=age)
        except CommandError:
            raise
        except Exception:
            raise CommandError("Nie można odczytać pełnej kopii.") from None
        self.stdout.write(
            json.dumps(
                {
                    "status": "ok",
                    "files": len(manifest["files"]),
                    "bytes": manifest["total_bytes"],
                    "snapshot_at": manifest["snapshot_at"],
                }
            )
        )
