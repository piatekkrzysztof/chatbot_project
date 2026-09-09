from pathlib import Path

from django.core.management.base import BaseCommand

from accounts.backups import decrypt_backup, read_backup, write_new_file


class Command(BaseCommand):
    help = "Odszyfrowuje kopię do nowego lokalnego JSON; nie zmienia bazy danych."

    def add_arguments(self, parser):
        parser.add_argument("input")
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        with Path(options["input"]).open("rb") as stream:
            data = decrypt_backup(read_backup(stream, encrypted=True))
        write_new_file(options["output"], data)
        self.stdout.write(
            "Odszyfrowano do wskazanego pliku. JSON zawiera sekrety; chroń go jak bazę."
        )
