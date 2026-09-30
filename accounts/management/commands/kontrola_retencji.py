"""Preflight migracji A05. Tylko raport, bez zmiany polityki i bez usuwania."""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from accounts.models import Tenant
from accounts.retencja_rozmow import MAX_RETENTION_DAYS


class Command(BaseCommand):
    help = "Sprawdza istniejące okresy retencji przed migracją ograniczenia zakresu."

    def handle(self, *args, **options):
        bledne = Tenant.objects.filter(
            Q(data_retention_days__gt=MAX_RETENTION_DAYS) | Q(data_retention_days__lt=0)
        )
        liczba = bledne.count()
        for pk, dni in bledne.order_by("pk").values_list("pk", "data_retention_days")[:100]:
            self.stdout.write(f"tenant={pk} data_retention_days={dni}")
        if liczba:
            raise CommandError(
                f"Nieprawidłowa retencja u {liczba} firm. "
                "Uzgodnij okres przed migracją; niczego nie zmieniono."
            )
        self.stdout.write("Retencja w obsługiwanym zakresie 0–3650. Niczego nie zmieniono.")
