"""Read-only queue check; does not retry, send messages or remove records."""

import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count
from django.utils import timezone

from accounts.security_notifications import PasswordNotification


class Command(BaseCommand):
    help = (
        "Sprawdza zaległe/nieudane powiadomienia o zmianie hasła; bez wysyłki i danych osobowych."
    )

    def handle(self, *args, **options):
        notices = PasswordNotification.objects.all()
        counts = dict(notices.values_list("status").annotate(total=Count("id")))
        overdue = notices.filter(
            status__in=[PasswordNotification.Status.PENDING, PasswordNotification.Status.SENDING],
            created_at__lt=timezone.now() - timedelta(minutes=10),
        ).count()
        failed = counts.get(PasswordNotification.Status.FAILED, 0)
        self.stdout.write(json.dumps({"counts": counts, "overdue": overdue}, sort_keys=True))
        if failed or overdue:
            raise CommandError("Powiadomienia wymagają obsługi: failed lub starsze niż 10 minut.")
