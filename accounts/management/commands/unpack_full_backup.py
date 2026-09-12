from django.core.management.base import BaseCommand, CommandError

from accounts.full_backups import unpack_bundle


class Command(BaseCommand):
    help = "Rozpakowuje pełną kopię do nowego prywatnego katalogu; nie modyfikuje bazy ani R2."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("source")
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        try:
            with open(options["source"], "rb") as stream:
                manifest = unpack_bundle(stream, options["output"])
        except CommandError:
            raise
        except Exception:
            raise CommandError(
                "Nie można rozpakować kopii; częściowy katalog nie jest gotowy do odtworzenia."
            ) from None
        self.stdout.write(
            f"Zweryfikowano i rozpakowano {len(manifest['files'])} plików oraz database.json. "
            "Baza nie została zmieniona."
        )
