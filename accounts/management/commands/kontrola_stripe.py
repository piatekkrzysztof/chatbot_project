"""Raport lokalny; uzgodnienie jednej firmy wyłącznie po --uzgodnij."""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from accounts.tasks_stripe import _kontroluj, kandydaci


class Command(BaseCommand):
    help = "Raport kontroli Stripe. --check kończy się błędem przy zaległościach powyżej doby."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int)
        parser.add_argument("--uzgodnij", action="store_true")
        parser.add_argument("--check", action="store_true")

    def handle(self, *args, **options):
        firmy = kandydaci()
        if options["tenant"] is not None:
            firmy = firmy.filter(pk=options["tenant"])
        if options["uzgodnij"]:
            if options["tenant"] is None:
                raise CommandError("--uzgodnij wymaga --tenant")
            tenant = firmy.first()
            if tenant is None:
                raise CommandError("Brak firmy z zapisanym powiązaniem Stripe")
            _kontroluj(tenant)
        prog = timezone.now() - timedelta(days=1)
        zalegle = firmy.filter(
            Q(kontrola_stripe__uzgodniono_at__isnull=True)
            | Q(kontrola_stripe__uzgodniono_at__lt=prog)
            | Q(kontrola_stripe__blad__gt="")
        )
        liczba = zalegle.count()
        self.stdout.write(f"Firmy powiązane: {firmy.count()}; wymagające kontroli: {liczba}")
        for tenant in zalegle.select_related("kontrola_stripe").order_by("pk")[:100]:
            kontrola = getattr(tenant, "kontrola_stripe", None)
            self.stdout.write(
                f"tenant={tenant.pk} ostatni_sukces={getattr(kontrola, 'uzgodniono_at', None)} "
                f"blad={getattr(kontrola, 'blad', '') or 'brak_aktualnego_potwierdzenia'}"
            )
        if options["check"] and liczba:
            raise CommandError("Kontrola Stripe wymaga reakcji; szczegóły powyżej")
