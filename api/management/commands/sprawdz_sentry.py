"""
Próba Sentry: jedno zdarzenie, wysłane z TEJ usługi.

Zastępuje publiczny adres `/sentry-debug/` (do 2.32.5). Tamten odpowiadał
każdemu, bez limitu, a każde wejście kosztowało zdarzenie z miesięcznej puli
planu - wystarczyła pętla w przeglądarce, żeby prawdziwe błędy produkcji
przestały docierać do końca miesiąca. Polecenie uruchamia tylko ktoś
z dostępem do powłoki Rendera.

Zdarzenie idzie na poziomie ERROR, bo tylko takie budzą alerty - próba ma
sprawdzić całą drogę, łącznie z mailem, a nie samo przyjęcie przez Sentry.
"""

import sentry_sdk
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Wysyła jedno zdarzenie próbne do Sentry i podaje jego numer."

    def handle(self, *args, **options):
        if not sentry_sdk.is_initialized():
            # Błąd, nie ostrzeżenie: cichy sukces bez Sentry wyglądałby jak
            # działający monitoring, a to dokładnie ta pomyłka, którą próba
            # ma wykluczyć.
            raise CommandError(
                "Sentry nie jest włączone w tym procesie. Sprawdź SENTRY_DSN; "
                "lokalnie Sentry startuje tylko z RENDER=1 (chatbot_project/observability.py)."
            )

        numer = sentry_sdk.capture_message(
            "Próba Sentry z polecenia sprawdz_sentry - to nie jest awaria", level="error"
        )
        sentry_sdk.flush(timeout=10)
        self.stdout.write(f"Wysłano zdarzenie próbne do Sentry: {numer}")
