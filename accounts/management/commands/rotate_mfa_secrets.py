from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import CustomUser, DrugiSkladnik


class Command(BaseCommand):
    help = "Re-encrypt MFA seeds with the current key; old key must remain in fallbacks."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        count = 0
        for user_id in DrugiSkladnik.objects.values_list("uzytkownik_id", flat=True).iterator():
            with transaction.atomic():
                CustomUser.objects.select_for_update().filter(pk=user_id).first()
                factor = (
                    DrugiSkladnik.objects.select_for_update()
                    .filter(
                        uzytkownik_id=user_id,
                    )
                    .first()
                )
                if factor is not None:
                    if not options["dry_run"]:
                        factor.save(update_fields=["sekret"])
                    count += 1
        self.stdout.write(f"MFA seeds: {count}; dry_run={options['dry_run']}")
