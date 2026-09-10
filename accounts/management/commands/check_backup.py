"""Odczytowa kontrola kopii; niezerowy kod wyjścia uruchamia alarm schedulera."""

import json
import math

from django.core.management.base import BaseCommand, CommandError

from accounts.backups import (
    backup_cipher,
    check_backup_age,
    latest_remote_backup,
    private_backup_storage,
    read_remote_backup,
)


class Command(BaseCommand):
    help = "Sprawdza integralność i wiek ostatniej kopii w private_backups, bez zapisu danych."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-age-hours",
            type=float,
            default=30,
            help="Maksymalny wiek kopii w godzinach (domyślnie 30).",
        )

    def handle(self, *args, **options):
        hours = options["max_age_hours"]
        if not math.isfinite(hours) or not 0 < hours <= 24 * 365:
            raise CommandError(
                "--max-age-hours musi być liczbą większą od 0 i nie większą niż 8760."
            )
        backup_cipher()
        storage = private_backup_storage()
        name = latest_remote_backup(storage)
        data = read_remote_backup(storage, name)
        result = check_backup_age(data, hours * 3600)
        self.stdout.write(json.dumps(result, sort_keys=True))
