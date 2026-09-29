"""
Sprzątanie archiwum kopii zapasowych. Domyślnie tylko liczy.

Kasowanie wymaga jawnego `--wykonaj`. To jedyne miejsce w systemie, które usuwa
dane nieodwracalnie i bez żadnej drugiej szansy: kopii zapasowej kopii nie ma.
Domyślna próba kosztuje jedno dodatkowe uruchomienie, a pomyłka bez niej
kosztuje archiwum.

Nie ma tego w harmonogramie i nie powinno się tam znaleźć bez osobnej decyzji
właściciela. Kopie powstają dziś ręcznie, raz w miesiącu; automat kasujący przy
ręcznym tworzeniu to układ, w którym jedna strona działa zawsze, a druga tylko
wtedy, gdy ktoś pamięta.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts import retencja_kopii
from accounts.backups import private_backup_storage


class Command(BaseCommand):
    help = "Usuwa stare kopie z archiwum. Bez --wykonaj tylko wypisuje, co by zniknęło."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--wykonaj", action="store_true")
        parser.add_argument(
            "--rodzaj",
            choices=sorted(retencja_kopii.ARCHIWA),
            help="Tylko to archiwum; domyślnie oba.",
        )

    def handle(self, *args, **options):
        magazyn = private_backup_storage()
        teraz = timezone.now()
        rodzaje = [options["rodzaj"]] if options["rodzaj"] else sorted(retencja_kopii.ARCHIWA)
        wykonaj = options["wykonaj"]

        razem = 0
        for rodzaj in rodzaje:
            okres = retencja_kopii.OKRESY[rodzaj].days
            nazwy = retencja_kopii.usun(magazyn, rodzaj, teraz=teraz, wykonaj=wykonaj)
            razem += len(nazwy)
            self.stdout.write(
                f"{rodzaj}: {len(nazwy)} kopii starszych niż {okres} dni "
                f"({'usunięto' if wykonaj else 'PRÓBA, nic nie usunięto'})"
            )
            for nazwa in nazwy:
                self.stdout.write(f"   {nazwa}")

        if not wykonaj:
            self.stdout.write(
                f"\nRazem do usunięcia: {razem}. Nic nie zostało usunięte - "
                "powtórz z --wykonaj, jeśli ta lista się zgadza."
            )
        else:
            self.stdout.write(f"\nUsunięto kopii: {razem}.")
        self.stdout.write(
            f"Niezależnie od wieku zostaje {retencja_kopii.MINIMUM_KOPII} najnowsze kopie "
            "w każdym archiwum."
        )
