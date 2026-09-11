from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import MfaChallenge


class Command(BaseCommand):
    help = "Remove MFA login challenges expired for at least 24 hours."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        rows = MfaChallenge.objects.filter(expires_at__lt=timezone.now() - timedelta(days=1))
        count = rows.count()
        if not options["dry_run"]:
            rows.delete()
        self.stdout.write(f"MFA challenges: {count}; dry_run={options['dry_run']}")
