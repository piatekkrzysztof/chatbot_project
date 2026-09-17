"""
Kontrola najnowszej pełnej kopii; niezerowy kod wyjścia uruchamia alarm.

`check_backup` pilnuje starego formatu (`backup_data`, zrzut samych danych).
Pełna kopia z bajtami plików (`backup_full`, format `.saas`) nie miała żadnej
kontroli, która sama znajdzie najnowszą - `verify_full_backup` wymaga podania
nazwy, więc nadaje się do sprawdzenia konkretnego pliku, a nie do harmonogramu.

Tu wystarczy uruchomić polecenie. Brak pełnych kopii jest błędem, nie ciszą:
magazyn, w którym nigdy nic się nie pojawiło, wygląda tak samo jak działający
harmonogram, dopóki ktoś nie zapyta wprost.

Polecenie tylko czyta: nie dotyka bazy, nie zapisuje plików i nie usuwa kopii.
"""

import json
import math

from django.core.management.base import BaseCommand, CommandError

from accounts.backups import private_backup_storage
from accounts.full_backups import najnowsza_pelna_kopia, verify_bundle


class Command(BaseCommand):
    help = "Sprawdza najnowszą pełną kopię w prywatnym magazynie: szyfrowanie, komplet i wiek."
    requires_system_checks = []

    def add_arguments(self, parser):
        # Pełna kopia wymaga wstrzymania zapisów (`--source-quiesced`), więc
        # powstaje w uzgodnionym oknie, a nie co noc. Domyślny próg to 31 dni:
        # pilnuje, że okno w ogóle się odbyło, zamiast udawać kopię dzienną.
        parser.add_argument("--max-age-hours", type=float, default=744)

    def handle(self, *args, **options):
        wiek = options["max_age_hours"]
        if not math.isfinite(wiek) or not 0 < wiek <= 8760:
            raise CommandError("--max-age-hours musi być większe od 0 i nie większe niż 8760.")
        magazyn = private_backup_storage()
        nazwa = najnowsza_pelna_kopia(magazyn)
        try:
            stream = magazyn.open(nazwa, "rb")
        except Exception:
            # Wyjątki dostawcy potrafią nieść podpisany URL albo identyfikator klucza.
            raise CommandError("Nie można odczytać pełnej kopii z prywatnego magazynu.") from None
        with stream:
            manifest = verify_bundle(stream, max_age_hours=wiek)
        self.stdout.write(
            json.dumps(
                {
                    "status": "ok",
                    "name": nazwa,
                    "snapshot_at": manifest["snapshot_at"],
                    "files": len(manifest["files"]),
                    "bytes": manifest["total_bytes"],
                },
                sort_keys=True,
            )
        )
