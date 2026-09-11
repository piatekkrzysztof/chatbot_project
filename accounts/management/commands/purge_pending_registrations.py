from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import PendingRegistration


class Command(BaseCommand):
    help = "Remove signup intents older than seven days; never touches accounts."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        expired = PendingRegistration.objects.filter(
            created_at__lt=timezone.now() - timedelta(days=7)
        )
        count = expired.count()
        if not options["dry_run"]:
            expired.delete()
        self.stdout.write(f"Pending registrations: {count}; dry_run={options['dry_run']}")
