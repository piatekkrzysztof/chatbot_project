"""
Zrzut danych aplikacji do pliku.

Darmowa baza na Renderze nie ma żadnych kopii zapasowych i wygasa 30 dni po
utworzeniu — dokumentacja Rendera mówi to wprost. Ta komenda zdejmuje zależność
od planu bazy: najgorszy scenariusz to odtworzenie z pliku, a nie zaczynanie
od zera.

Pomijamy tabele, które migracje i tak odtwarzają (typy zawartości, uprawnienia,
sesje, log adminstracyjny). Ich zrzut nie tylko zajmuje miejsce, ale przy
odtwarzaniu koliduje z rekordami tworzonymi przez migracje.
"""
import datetime
import io
import os

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

# Odtwarzane przez migracje — w zrzucie tylko przeszkadzają
POMIJANE = [
    "contenttypes",
    "auth.permission",
    "sessions",
    "admin.logentry",
]


class Command(BaseCommand):
    help = (
        "Zapisuje dane aplikacji do pliku JSON. Odtworzenie: "
        "manage.py loaddata <plik>"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            help="Ścieżka pliku. Domyślnie backups/kopia-RRRRMMDD-GGMM.json",
        )
        parser.add_argument(
            "--to-storage",
            action="store_true",
            help=(
                "Wyślij kopię do skonfigurowanego magazynu obiektowego "
                "(R2/S3). Bez tego plik zostaje na dysku, który na Renderze "
                "znika przy wdrożeniu."
            ),
        )

    def handle(self, *args, **options):
        znacznik = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        sciezka = options.get("output") or os.path.join(
            "backups", f"kopia-{znacznik}.json"
        )

        katalog = os.path.dirname(sciezka)
        if katalog:
            os.makedirs(katalog, exist_ok=True)

        bufor = io.StringIO()
        call_command(
            "dumpdata",
            *[f"--exclude={etykieta}" for etykieta in POMIJANE],
            indent=2,
            stdout=bufor,
        )
        tresc = bufor.getvalue()

        if not tresc.strip() or tresc.strip() == "[]":
            raise CommandError(
                "Zrzut jest pusty — przerywam, żeby nie nadpisać dobrej kopii pustą."
            )

        with open(sciezka, "w", encoding="utf-8") as plik:
            plik.write(tresc)

        rozmiar = os.path.getsize(sciezka)
        liczba_obiektow = tresc.count('"model":')
        self.stdout.write(self.style.SUCCESS(f"Zapisano: {sciezka}"))
        self.stdout.write(f"  rozmiar: {rozmiar / 1024:.1f} kB")
        self.stdout.write(f"  obiektów: {liczba_obiektow}")

        if options["to_storage"]:
            nazwa = f"backups/{os.path.basename(sciezka)}"
            zapisana = default_storage.save(nazwa, ContentFile(tresc.encode("utf-8")))
            self.stdout.write(
                self.style.SUCCESS(f"Wysłano do magazynu: {zapisana}")
            )
            if default_storage.__class__.__name__ == "FileSystemStorage":
                self.stdout.write(self.style.WARNING(
                    "  Uwaga: magazynem jest dysk lokalny, a nie R2/S3. "
                    "Na Renderze taki plik znika przy wdrożeniu."
                ))

        self.stdout.write("")
        self.stdout.write(f"Odtworzenie: manage.py loaddata {sciezka}")
