"""Password-only recovery; MFA stays enabled and no session is issued."""

from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework.exceptions import ValidationError

from accounts.models import CustomUser
from accounts.security_notifications import record_password_change
from accounts.sessions import LoginSession

RECEIPT = "Jeśli konto może odzyskać dostęp, wyślemy na podany adres link do zmiany hasła."
INVALID = "Link wygasł lub został użyty. Poproś o nowy link."
generator = PasswordResetTokenGenerator()


class DeliveryUnavailable(Exception):
    pass


def reset_url(user):
    base = settings.FRONTEND_URL.rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme not in ("https", "http")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or (not settings.DEBUG and parsed.scheme != "https")
    ):
        raise DeliveryUnavailable("Password recovery delivery unavailable")
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    return f"{base}/reset-hasla#uid={uid}&token={generator.make_token(user)}"


def deliver_reset(email):
    user = CustomUser.objects.filter(email__iexact=email, is_active=True).first()
    if user is None or not user.has_usable_password():
        return
    try:
        sent = send_mail(
            "Zmiana hasła — Chatbot SaaS",
            "Aby ustawić nowe hasło, otwórz link poniżej. Jest jednorazowy i ważny 30 minut. "
            "Samo otwarcie linku nie zmienia hasła.\n\n"
            f"{reset_url(user)}\n\n"
            "Jeśli to nie Ty prosisz o zmianę, zignoruj tę wiadomość. "
            "Logowanie dwuetapowe pozostaje włączone, jeśli było skonfigurowane.",
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
        if sent != 1:
            raise DeliveryUnavailable("Password recovery delivery unavailable")
    except Exception:
        # No SMTP reply, address or reset link in a task's exception message.
        raise DeliveryUnavailable("Password recovery delivery unavailable") from None


def reset_user(uid, token, *, lock=False):
    try:
        decoded = urlsafe_base64_decode(uid).decode("ascii")
        if not decoded.isdecimal() or len(decoded) > 19 or int(decoded) > 2**63 - 1:
            raise ValueError
        query = CustomUser.objects
        if lock:
            query = query.select_for_update()
        user = query.filter(pk=int(decoded), is_active=True).first()
    except (ValueError, TypeError, UnicodeError, OverflowError):
        user = None
    if user is None or not user.has_usable_password() or not generator.check_token(user, token):
        raise ValidationError({"token": INVALID})
    return user


@transaction.atomic
def confirm_reset(uid, token, password):
    # Serializes reset, login and refresh. The token is rechecked on current
    # password/email/last_login after acquiring the account row.
    user = reset_user(uid, token, lock=True)
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        raise ValidationError({"password": exc.messages}) from None
    user.set_password(password)
    user.save(update_fields=["password"])
    record_password_change(user)
    LoginSession.objects.filter(user=user, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    # No JWT, login, cookie mutation, MFA removal or account activation here.
