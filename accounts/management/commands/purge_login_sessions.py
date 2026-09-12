from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.sessions import LoginSession


class Command(BaseCommand):
    help = "Remove login sessions expired for at least 24 hours, in bounded batches."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        rows = LoginSession.objects.filter(expires_at__lt=timezone.now() - timedelta(days=1))
        if options["dry_run"]:
            count = rows.count()
        else:
            count = 0
            while batch := list(rows.values_list("pk", flat=True)[:1000]):
                deleted, _ = LoginSession.objects.filter(pk__in=batch).delete()
                count += deleted
        self.stdout.write(f"Login sessions: {count}; dry_run={options['dry_run']}")
