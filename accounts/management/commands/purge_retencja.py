"""
Sprzątanie po okresach przechowywania. To polecenie naprawdę usuwa.

Warunki i okresy czyta z `accounts/retencja.py`, czyli z tego samego miejsca,
co `raport_retencji` - dwie kopie tej samej reguły rozjeżdżają się po cichu.

`--dry-run` liczy, nie usuwa. Przed pierwszym przebiegiem na produkcji sprawdź
nim liczby: raport i tryb próbny muszą się zgadzać, a jeśli którakolwiek liczba
zaskakuje, to jest moment, żeby to wyjaśnić - nie po usunięciu.

Nocne zadanie z harmonogramu woła tę samą funkcję, nie to polecenie.
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts import retencja


class Command(BaseCommand):
    help = "Usuwa dane po okresie przechowywania. --dry-run tylko liczy."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--rodzaj",
            choices=sorted(retencja.REGULY),
            help="Tylko ten rodzaj danych; domyślnie wszystkie.",
        )

    def handle(self, *args, **options):
        proba = options["dry_run"]
        rodzaj = options["rodzaj"]
        if rodzaj and rodzaj not in retencja.REGULY:
            raise CommandError(f"Nieznany rodzaj danych: {rodzaj}")

        teraz = timezone.now()
        klucze = [rodzaj] if rodzaj else list(retencja.REGULY)
        wyniki = {klucz: retencja.usun(klucz, teraz=teraz, proba=proba) for klucz in klucze}

        tryb = "PRÓBA, nic nie usunięto" if proba else "usunięto"
        for klucz, ile in wyniki.items():
            self.stdout.write(f"{retencja.NAZWY[klucz]}: {ile} ({tryb})")
        self.stdout.write(f"Razem: {sum(wyniki.values())} ({tryb})")
