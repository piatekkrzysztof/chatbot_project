"""Short database transactions around admission/settlement, never around AI calls."""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from accounts.models import MessageReservation, Subscription, Tenant
from accounts.odmowy import PowodOdmowy, zapisz_odmowe
from accounts.plans import rate_for

logger = logging.getLogger(__name__)


class ChatAdmissionDenied(APIException):
    status_code = 429

    def __init__(self, message, *, permanent=False, status=429):
        self.status_code = status
        super().__init__(
            {
                "error": message,
                "kod": "czat_niedostepny" if permanent else "czat_chwilowo_zajety",
            }
        )


def reserve_message(tenant, *, is_test=False):
    """All endpoints for one tenant share this lock, including the free test chat."""
    with transaction.atomic():
        Tenant.objects.select_for_update().get(pk=tenant.pk)
        now = timezone.now()
        reservations = MessageReservation.objects.filter(tenant=tenant)
        # A dead worker's call might have reached OpenAI. Never silently refund it.
        expired = reservations.filter(state="pending", expires_at__lte=now).update(
            state="uncertain"
        )
        if expired:
            logger.warning(
                "Expired AI reservations require reconciliation: tenant=%s count=%s",
                tenant.pk,
                expired,
            )

        denied = None
        try:
            reservation = _reserve_locked(tenant, reservations, now, is_test)
        except ChatAdmissionDenied as exc:
            denied = exc
    if denied:
        if denied.detail["kod"] == "czat_niedostepny":
            try:
                zapisz_odmowe(
                    tenant,
                    PowodOdmowy.LIMIT_WIADOMOSCI
                    if denied.status_code == 429
                    else PowodOdmowy.SUBSKRYPCJA_WYGASLA,
                )
            except Exception:
                logger.exception("Could not record chat admission denial")
        raise denied
    return Reservation(reservation)


def _reserve_locked(tenant, reservations, now, is_test):
    # DRF's cache throttles are best-effort; paid attempts need a shared atomic cap.
    plan = Subscription.objects.filter(tenant=tenant).values_list("plan_type", flat=True).first()
    per_minute = int(rate_for(plan).split("/")[0])
    if reservations.filter(created_at__gt=now - timedelta(minutes=1)).count() >= per_minute:
        raise ChatAdmissionDenied("Zbyt wiele wiadomości. Spróbuj za minutę.")
    subscription = None
    if not is_test:
        subscription = Subscription.objects.select_for_update().filter(tenant=tenant).first()
        if not subscription or not (
            subscription.is_active
            and subscription.start_date <= now.date() <= subscription.end_date
        ):
            raise ChatAdmissionDenied("Subscription expired", permanent=True, status=403)
        subscription.reset_usage(only_if_due=True)
        held = reservations.filter(
            subscription=subscription,
            cycle_id=subscription.billing_cycle_id,
            state__in=["pending", "uncertain"],
        ).count()
        if subscription.current_message_count + held >= subscription.message_limit:
            raise ChatAdmissionDenied("Message limit exceeded", permanent=True)
    else:
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if (
            reservations.filter(is_test=True, created_at__gte=day_start).count()
            >= settings.CHAT_TEST_DAILY_LIMIT
        ):
            raise ChatAdmissionDenied("Wykorzystano dzisiejszy limit testów bota. Spróbuj jutro.")

    if (
        reservations.filter(finished=False, expires_at__gt=now).count()
        >= settings.CHAT_MAX_CONCURRENT
    ):
        raise ChatAdmissionDenied("Bot obsługuje teraz inne wiadomości. Spróbuj za chwilę.")
    reservation = MessageReservation.objects.create(
        tenant=tenant,
        subscription=subscription,
        cycle_id=subscription.billing_cycle_id if subscription else None,
        is_test=is_test,
        expires_at=now + timedelta(seconds=settings.CHAT_RESERVATION_SECONDS),
    )
    return reservation


def _notify(subscription_id, threshold):
    from accounts.tasks import powiadom_o_zuzyciu
    from documents.utils.queue import enqueue

    try:
        enqueue(powiadom_o_zuzyciu, subscription_id, threshold)
    except Exception:
        logger.exception("Could not enqueue usage alert: subscription=%s", subscription_id)


class Reservation:
    def __init__(self, row):
        self.row = row

    def check_start(self):
        # A delayed/unconsumed response cannot begin AI work after its lease expired.
        if timezone.now() >= self.row.expires_at:
            self.settle(False)
            raise ChatAdmissionDenied("Upłynął czas oczekiwania na odpowiedź. Spróbuj ponownie.")

    def charge(self):
        self.settle(True)

    def settle(self, billable):
        with transaction.atomic():
            Tenant.objects.select_for_update().get(pk=self.row.tenant_id)
            subscription = None
            if self.row.subscription_id:
                subscription = (
                    Subscription.objects.select_for_update()
                    .filter(pk=self.row.subscription_id)
                    .first()
                )
            row = MessageReservation.objects.select_for_update().get(pk=self.row.pk)
            if not billable:
                row.finished = True
                row.save(update_fields=["finished"])
            if row.state not in ("pending", "uncertain"):
                return
            row.state = "uncertain" if billable is None else ("charged" if billable else "released")
            row.save(update_fields=["state"])
            if billable and subscription and subscription.billing_cycle_id == row.cycle_id:
                subscription.current_message_count += 1
                threshold = subscription.prog_do_powiadomienia()
                if threshold:
                    subscription.alert_threshold_sent = threshold
                    transaction.on_commit(lambda: _notify(subscription.pk, threshold))
                subscription.save(update_fields=["current_message_count", "alert_threshold_sent"])


class ReservedStream:
    """close() also handles a StreamingHttpResponse which was never iterated."""

    def __init__(self, stream, reservation):
        self.stream = iter(stream)
        self.reservation = reservation
        self.started = False
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.closed:
            raise StopIteration
        try:
            if not self.started:
                self.reservation.check_start()
                self.started = True
            return next(self.stream)
        except StopIteration:
            self.close()
            raise
        except BaseException:
            self.close(uncertain=True)
            raise

    def close(self, *, uncertain=False):
        if self.closed:
            return
        self.closed = True
        try:
            close = getattr(self.stream, "close", None)
            if close:
                close()
        except BaseException:
            uncertain = True
            raise
        finally:
            # charge() is idempotent; releasing an already charged ticket is a no-op.
            self.reservation.settle(None if uncertain else False)
