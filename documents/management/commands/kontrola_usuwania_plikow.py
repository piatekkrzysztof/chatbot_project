from django.core.management.base import BaseCommand, CommandError

from documents.models import UsunieciePliku
from documents.usuwanie_plikow import (
    ZAKONCZONE,
    BlokadaUsuniecia,
    cel_magazynu,
    ponow_usuniecie,
    zalegle,
)


class Command(BaseCommand):
    help = "Raport zaległych usunięć plików. Domyślnie tylko odczyt, bez nazw i sekretów."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--magazyny", action="store_true", help="Tylko skróty tożsamości magazynów."
        )
        group.add_argument(
            "--ponow", type=int, help="Jawnie ponów jedno zlecenie po usunięciu przyczyny."
        )

    def handle(self, *args, **options):
        if options["magazyny"]:
            for alias in ("default", "private_documents"):
                self.stdout.write(f"{alias} cel={cel_magazynu(alias)}")
            return
        if options["ponow"] is not None:
            try:
                ponow_usuniecie(options["ponow"])
            except (UsunieciePliku.DoesNotExist, BlokadaUsuniecia) as error:
                raise CommandError("Nie można ponowić zlecenia: " + type(error).__name__) from error
            self.stdout.write(
                "Zlecenie czeka na najbliższy obchód; nie kasowano plików w komendzie."
            )
            return
        pending = UsunieciePliku.objects.exclude(stan__in=ZAKONCZONE)
        self.stdout.write(f"Niezakończone zlecenia: {pending.count()}")
        for job in pending.order_by("utworzono_at", "pk")[:100]:
            self.stdout.write(
                f"id={job.pk} stan={job.stan} proby={job.proby} "
                f"kod={job.blad or '-'} utworzono={job.utworzono_at.isoformat()}"
            )
        if zalegle().exists():
            raise CommandError("Zaległe lub zablokowane usunięcia wymagają reakcji operatora.")
