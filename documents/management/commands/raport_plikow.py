import json

from django.core.management.base import BaseCommand, CommandError

from documents.raport_plikow import PREFIKSY, raport


class Command(BaseCommand):
    help = "Raport metadanych dokumentów/brandingu. Nie kasuje plików ani nie zapisuje zleceń."

    def add_arguments(self, parser):
        parser.add_argument("--magazyn", required=True, choices=PREFIKSY)
        parser.add_argument("--limit", type=int, default=10000)
        parser.add_argument("--sekundy", type=int, default=60)
        parser.add_argument(
            "--wiek", type=int, default=24, help="Minimalny wiek w godzinach, 1–8760."
        )
        parser.add_argument(
            "--probka", type=int, default=100, help="Do 1000 pozycji, 0 wyłącza listę."
        )
        parser.add_argument(
            "--nazwy",
            action="store_true",
            help="Jawnie dołącz nazwy obiektów do próbki; wynik może zawierać dane osobowe.",
        )

    def handle(self, *args, **options):
        try:
            result = raport(
                options["magazyn"],
                limit=options["limit"],
                sekundy=options["sekundy"],
                wiek=options["wiek"],
                probka=options["probka"],
                nazwy=options["nazwy"],
            )
        except ValueError:
            raise CommandError(
                "Limity: obiekty 1–100000, sekundy 1–300, wiek 1–8760, próbka 0–1000."
            ) from None
        # JSON koduje również znaki sterujące w historycznych nazwach plików.
        self.stdout.write(json.dumps(result, ensure_ascii=True, indent=2))
        if not result["pelny_zakres_prefiksow"]:
            raise CommandError("Raport niepełny; kod: " + result["kod"])
