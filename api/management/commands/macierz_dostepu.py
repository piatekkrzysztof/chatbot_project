"""
Buduje macierz dostępu (F01) z kontraktu dostępu.

    python manage.py macierz_dostepu            # wypisuje tabelę
    python manage.py macierz_dostepu --zapisz   # nadpisuje docs/macierz-dostepu.md

Po dodaniu trasy: wpis w api/kontrakt_dostepu.py, potem --zapisz. Test
api/tests/test_macierz_dostepu.py zatrzyma CI, jeśli dokument się rozjedzie.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from api.macierz_dostepu import SCIEZKA_DOKUMENTU, zbuduj_macierz


class Command(BaseCommand):
    help = "Buduje docs/macierz-dostepu.md z kontraktu dostępu (nic poza tym nie zmienia)."

    def add_arguments(self, parser):
        parser.add_argument("--zapisz", action="store_true", help=f"Zapisz do {SCIEZKA_DOKUMENTU}.")

    def handle(self, *args, **opcje):
        tresc = zbuduj_macierz()
        if not opcje["zapisz"]:
            self.stdout.write(tresc)
            return
        plik = Path(settings.BASE_DIR) / SCIEZKA_DOKUMENTU
        plik.write_text(tresc, encoding="utf-8", newline="\n")
        self.stdout.write(self.style.SUCCESS(f"Zapisano {SCIEZKA_DOKUMENTU}."))
