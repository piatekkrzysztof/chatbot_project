from django.core.management.base import BaseCommand

from accounts.models import Tenant
from accounts.retencja_rozmow import poprawne_dni
from chat.retention import purge_all_tenants, purge_tenant


class Command(BaseCommand):
    help = (
        "Usuwa dane rozmów starsze niż okres retencji ustawiony u każdego klienta. "
        "Odpowiednik zadania Celery — do uruchomienia tam, gdzie nie ma workera."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--company",
            help="Ogranicz czyszczenie do jednej firmy (nazwa).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Pokaż, ile rekordów zostałoby usuniętych, bez kasowania.",
        )

    def handle(self, *args, **options):
        if options["dry_run"]:
            self._report_only(options.get("company"))
            return

        if options.get("company"):
            tenant = Tenant.objects.get(name=options["company"])
            removed = purge_tenant(tenant)
        else:
            removed = purge_all_tenants()

        if not removed:
            self.stdout.write("Nie było nic do usunięcia.")
            return

        self.stdout.write(self.style.SUCCESS("Usunięto:"))
        for model, count in sorted(removed.items()):
            self.stdout.write(f"  {model}: {count}")

    def _report_only(self, company):
        """Podgląd kryteriów wieku; równoległe zapisy i blokady mogą zmienić wynik."""
        from datetime import timedelta

        from django.utils import timezone

        from chat.models import ChatUsageLog, ContactRequest, Conversation, PromptLog

        tenants = Tenant.objects.all()
        if company:
            tenants = tenants.filter(name=company)

        for tenant in tenants:
            days = tenant.data_retention_days or 0
            if not poprawne_dni(days):
                self.stderr.write(f"tenant={tenant.pk}: nieobsługiwany okres retencji; pomijam.")
                continue
            if days <= 0:
                self.stdout.write(f"{tenant.name}: retencja wyłączona, pomijam.")
                continue

            cutoff = timezone.now() - timedelta(days=days)
            counts = {
                "PromptLog": PromptLog.objects.filter(tenant=tenant, created_at__lt=cutoff).count(),
                "ChatUsageLog": ChatUsageLog.objects.filter(
                    tenant=tenant, created_at__lt=cutoff
                ).count(),
                "ContactRequest": ContactRequest.objects.filter(
                    tenant=tenant, created_at__lt=cutoff
                ).count(),
                "Conversation": (
                    Conversation.objects.filter(tenant=tenant, last_message_at__lt=cutoff)
                    .exclude(messages__timestamp__gte=cutoff)
                    .exclude(promptlog__created_at__gte=cutoff)
                    .exclude(chatusagelog__created_at__gte=cutoff)
                    .exclude(contact_requests__created_at__gte=cutoff)
                    .count()
                ),
            }
            summary = ", ".join(f"{k}={v}" for k, v in counts.items() if v)
            self.stdout.write(
                f"{tenant.name} (retencja {days} dni): " + (summary or "nic do usunięcia")
            )
