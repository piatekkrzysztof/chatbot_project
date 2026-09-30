"""Przypina potwierdzoną sesję po utracie odpowiedzi; nigdy nie tworzy płatności."""

import stripe
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.checkout import ProbaZakupu


class Command(BaseCommand):
    help = "Sprawdź zgodność sesji Stripe z próbą zakupu. Zapis wyłącznie z --zapisz."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, required=True)
        parser.add_argument("--sesja", required=True)
        parser.add_argument("--zapisz", action="store_true")

    def handle(self, *args, **options):
        if not settings.STRIPE_SECRET_KEY:
            raise CommandError("Brak konfiguracji Stripe.")
        stripe.api_key = settings.STRIPE_SECRET_KEY
        try:
            sesja = stripe.checkout.Session.retrieve(options["sesja"])
        except stripe.StripeError as error:
            raise CommandError(
                "Nie udało się odczytać sesji Stripe; niczego nie zmieniono."
            ) from error
        with transaction.atomic():
            proba = (
                ProbaZakupu.objects.select_for_update().filter(tenant_id=options["tenant"]).first()
            )
            metadata = sesja.get("metadata") or {}
            if (
                proba is None
                or not proba.parametry
                or str(metadata.get("tenant_id")) != str(options["tenant"])
                or metadata.get("checkout_attempt") != str(proba.klucz)
                or sesja.get("id") != options["sesja"]
                or sesja.get("mode") != "subscription"
                or sesja.get("status") not in ("open", "expired", "complete")
                or (proba.sesja_id and proba.sesja_id != options["sesja"])
            ):
                raise CommandError("Sesja nie odpowiada bieżącej próbie zakupu; zapis odrzucony.")
            if options["zapisz"]:
                proba.sesja_id = options["sesja"]
                proba.save(update_fields=["sesja_id"])
                self.stdout.write("Zapisano powiązanie. Nie utworzono ani nie anulowano płatności.")
            else:
                self.stdout.write("Sesja zgodna. Niczego nie zapisano; zapis wymaga --zapisz.")
