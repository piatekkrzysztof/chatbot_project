"""Durable password-change receipts; SMTP is never called by the password transaction."""

import logging
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

from billiard.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.db import models, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
LEASE = timedelta(minutes=5)
BATCH_SIZE = 10


class PasswordNotification(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        SENDING = "sending"
        SENT = "sent"
        FAILED = "failed"

    id: models.UUIDField = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user: models.ForeignKey = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    recipient: models.EmailField = models.EmailField()
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    status: models.CharField = models.CharField(
        max_length=7, choices=Status.choices, default=Status.PENDING
    )
    attempts: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(default=0)
    available_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    claim: models.UUIDField = models.UUIDField(null=True)
    sent_at: models.DateTimeField = models.DateTimeField(null=True)
    # Fixed codes only, never the SMTP exception, address, password or reset token.
    last_error: models.CharField = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["status", "available_at"], name="password_notice_due")]


def record_password_change(user):
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Password notification requires the password transaction")
    # Freeze the recipient at the event, not at delivery after an address change.
    PasswordNotification.objects.create(user=user, recipient=user.email)


def claim_next():
    now = timezone.now()
    with transaction.atomic():
        notice = (
            PasswordNotification.objects.select_for_update(skip_locked=True)
            .filter(
                status__in=[
                    PasswordNotification.Status.PENDING,
                    PasswordNotification.Status.SENDING,
                ],
                available_at__lte=now,
            )
            .order_by("available_at", "id")
            .first()
        )
        if notice is None:
            return None
        if notice.attempts >= MAX_ATTEMPTS:
            notice.status = PasswordNotification.Status.FAILED
            notice.last_error = "attempts_exhausted"
            notice.claim = None
        else:
            notice.status = PasswordNotification.Status.SENDING
            notice.attempts += 1
            notice.claim = uuid.uuid4()
            notice.available_at = now + LEASE
        notice.save(update_fields=["status", "attempts", "claim", "available_at", "last_error"])
    if notice.status == PasswordNotification.Status.FAILED:
        logger.error("Password notification exhausted: %s", notice.pk)
    return notice


def deliver(notice):
    # This is not a recovery token/link; a configured trusted panel is the only destination.
    base = settings.FRONTEND_URL.rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or (not settings.DEBUG and parsed.scheme != "https")
    ):
        raise ValueError("Invalid notification configuration")
    changed_at = notice.created_at.astimezone(timezone.get_default_timezone())
    body = (
        "Hasło do Twojego konta Chatbot SaaS zostało zmienione.\n"
        f"Czas zmiany: {changed_at:%Y-%m-%d %H:%M:%S %Z}.\n\n"
        "Wszystkie wcześniejsze sesje logowania zostały zakończone. "
        "Logowanie dwuetapowe pozostaje włączone, jeśli było skonfigurowane.\n\n"
        "Jeśli to Ty zmieniłeś hasło, nie musisz nic robić. "
        "Jeśli nie rozpoznajesz tej zmiany, zabezpiecz swoją skrzynkę e-mail "
        "i skorzystaj z odzyskiwania hasła w panelu:\n"
        f"{base}/odzyskaj-haslo\n\n"
        "Jeżeli nadal nie możesz odzyskać dostępu, skontaktuj się z obsługą "
        "przez znany Ci kanał kontaktu. Nie przekazuj nikomu hasła ani kodów MFA."
    )
    # Finite socket waits; Celery's hard limit also bounds a stalled SMTP exchange.
    with get_connection(timeout=15) as connection:
        sent = EmailMessage(
            "Hasło zostało zmienione — Chatbot SaaS",
            body,
            settings.DEFAULT_FROM_EMAIL,
            [notice.recipient],
            connection=connection,
            headers={"Message-ID": f"<{notice.pk}@notifications.agencjasm-art.pl>"},
        ).send(fail_silently=False)
    if sent != 1:
        raise RuntimeError("Notification delivery unavailable")


def process_batch():
    processed = 0
    for _ in range(BATCH_SIZE):
        notice = claim_next()
        if notice is None:
            break
        processed += 1
        if notice.status == PasswordNotification.Status.FAILED:
            continue
        error = ""
        try:
            deliver(notice)
        except SoftTimeLimitExceeded:
            raise
        except Exception:
            # Do not expose provider replies in Celery/logs/Sentry or the outbox.
            error = "delivery_unavailable"
        terminal = bool(error and notice.attempts >= MAX_ATTEMPTS)
        status = (
            PasswordNotification.Status.FAILED
            if terminal
            else PasswordNotification.Status.PENDING
            if error
            else PasswordNotification.Status.SENT
        )
        now = timezone.now()
        updated = PasswordNotification.objects.filter(
            pk=notice.pk, status=PasswordNotification.Status.SENDING, claim=notice.claim
        ).update(
            status=status,
            sent_at=None if error else now,
            available_at=now + timedelta(seconds=min(60 * 2 ** (notice.attempts - 1), 3600)),
            claim=None,
            last_error=error,
        )
        if updated and error:
            log = logger.error if terminal else logger.warning
            log("Password notification delivery failed: %s; attempt=%s", notice.pk, notice.attempts)
    return processed
