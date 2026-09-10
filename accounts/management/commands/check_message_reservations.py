"""Report unresolved AI work; reconcile only an explicitly selected expired ticket."""

import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.message_quota import Reservation
from accounts.models import MessageReservation, Tenant


class Command(BaseCommand):
    help = "Report uncertain AI reservations, reconcile one, or prune old settled tickets."

    def add_arguments(self, parser):
        parser.add_argument("--reservation", type=uuid.UUID)
        parser.add_argument("--outcome", choices=["charged", "released"])
        parser.add_argument("--prune", action="store_true")

    def handle(self, *args, **options):
        ticket_id, outcome = options["reservation"], options["outcome"]
        if bool(ticket_id) != bool(outcome) or (ticket_id and options["prune"]):
            raise CommandError("Use --reservation UUID --outcome charged|released, or --prune.")
        now = timezone.now()
        if ticket_id:
            row = MessageReservation.objects.filter(pk=ticket_id).first()
            if row is None:
                raise CommandError("Reservation not found.")
            with transaction.atomic():
                Tenant.objects.select_for_update().get(pk=row.tenant_id)
                row.refresh_from_db()
                if row.expires_at > now:
                    raise CommandError("Reservation may still be running; wait until it expires.")
                if row.state not in ("pending", "uncertain", outcome):
                    raise CommandError("Reservation already has a different terminal outcome.")
                ticket = Reservation(row)
                ticket.settle(outcome == "charged")
                ticket.settle(False)
            self.stdout.write(f"Reconciled {ticket_id}: {outcome}")
            return

        if options["prune"]:
            # Keep unresolved outcomes and never delete tickets in an active quota cycle.
            from django.db.models import F

            rows = MessageReservation.objects.filter(
                finished=True,
                state__in=["charged", "released"],
                created_at__lt=now - timedelta(days=90),
            ).exclude(subscription__billing_cycle_id=F("cycle_id"))
            batch = list(rows.values_list("pk", flat=True)[:1000])
            count, _ = MessageReservation.objects.filter(pk__in=batch).delete()
            self.stdout.write(f"Pruned {count} settled reservations older than 90 days.")
            return

        unresolved = MessageReservation.objects.filter(
            Q(state="uncertain") | Q(state="pending", expires_at__lte=now)
        ).order_by("created_at")
        count = unresolved.count()
        for row in unresolved[:50]:
            self.stdout.write(
                f"{row.pk} tenant={row.tenant_id} state={row.state} "
                f"expires={row.expires_at.isoformat()}"
            )
        if count:
            raise CommandError(f"{count} AI reservations need reconciliation; showing at most 50.")
        self.stdout.write("OK: no unresolved AI reservations.")
