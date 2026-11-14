"""Email ownership before allocating an account, a company or a trial."""

import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac
from rest_framework.exceptions import APIException, ValidationError

from accounts.models import CustomUser, PendingRegistration

RECEIPT = "Jeśli rejestracja oczekuje na potwierdzenie, wyślemy link na podany adres."
INVALID = "Link wygasł lub został użyty. Poproś o nowy link albo zaloguj się."


class EmailUnavailable(APIException):
    status_code = 503
    default_detail = "Nie udało się wysłać wiadomości. Spróbuj ponownie za minutę."


def digest(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def activation_url(token):
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
        raise EmailUnavailable()
    # Fragment is never sent in the browser's HTTP request or Referer.
    return f"{base}/potwierdz-email#token={token}"


def adres_logowania():
    # Ta sama walidacja adresu panelu co dla linku potwierdzającego.
    return activation_url("x").split("/potwierdz-email", 1)[0] + "/login"


def powiadom_o_istniejacym_koncie(konto):
    """
    Mail do osoby, która próbuje zarejestrować adres mający już konto.

    Formularz rejestracji odpowiada wtedy tak samo jak dla nowego adresu
    (przegląd 2026-11, R17), więc jedynym miejscem, gdzie właściciel adresu
    może się dowiedzieć, że konto już ma, jest jego skrzynka. Jedna wiadomość
    na dobę na adres: formularz jest publiczny i nie może służyć do zasypywania
    cudzej skrzynki. Nieaktywne konto nie dostaje nic - nie ma się na co
    logować.
    """
    if not konto.is_active or not konto.email:
        return
    klucz = (
        "rejestracja-istnieje:"
        + salted_hmac("rejestracja-istnieje", konto.email.lower()).hexdigest()
    )
    try:
        if not cache.add(klucz, 1, timeout=24 * 3600):
            return
    except Exception:
        # Bez licznika nie wysyłamy: brak pamięci podręcznej nie może znaczyć
        # „bez limitu".
        return
    try:
        sent = send_mail(
            "Masz już konto — Chatbot SaaS",
            "Ktoś próbował założyć konto na ten adres e-mail, a konto już istnieje. "
            "Nowe konto nie powstało i nic się nie zmieniło.\n\n"
            f"Jeśli to Ty, zaloguj się: {adres_logowania()}\n"
            "Jeśli nie pamiętasz hasła, użyj na stronie logowania opcji "
            "„Nie pamiętam hasła”.\n\n"
            "Jeśli to nie Ty, zignoruj wiadomość.",
            settings.DEFAULT_FROM_EMAIL,
            [konto.email],
            fail_silently=False,
        )
        if sent != 1:
            raise EmailUnavailable()
    except Exception:
        # Jak przy linku potwierdzającym: awaria poczty daje tę samą odpowiedź
        # dla adresu z kontem i bez konta.
        cache.delete(klucz)
        raise EmailUnavailable() from None


def request_email(email, payload=None):
    """Lock per address; a profile change always rotates the confirmation token."""
    now = timezone.now()
    token = secrets.token_urlsafe(32)
    url = activation_url(token)
    konto = CustomUser.objects.filter(email__iexact=email).first()
    if konto is not None:
        # Tylko początek rejestracji; ponowna wysyłka linku (payload None)
        # dla adresu z kontem zostaje bez żadnej wiadomości.
        if payload is not None:
            powiadom_o_istniejacym_koncie(konto)
        return
    with transaction.atomic():
        if CustomUser.objects.filter(email__iexact=email).exists():
            return
        if payload is not None:
            PendingRegistration.objects.get_or_create(
                email=email,
                defaults={
                    "payload": payload,
                    "expires_at": now + timedelta(hours=24),
                    "window_start": now,
                },
            )
        pending = PendingRegistration.objects.select_for_update().filter(email=email).first()
        if pending is None or pending.used_at is not None:
            return
        if pending.created_at < now - timedelta(days=7):
            if payload is None:
                return
            pending.payload = payload
            pending.created_at = now
        if now >= pending.window_start + timedelta(days=1):
            pending.window_start = now
            pending.send_count = 0
        if pending.send_count >= 5 or (
            pending.sent_at is not None and now < pending.sent_at + timedelta(minutes=1)
        ):
            return
        if payload is not None:
            pending.payload = payload
        pending.token_digest = digest(token)
        pending.expires_at = now + timedelta(hours=24)
        pending.sent_at = now
        pending.send_count += 1
        pending.save()
    # SMTP runs after commit. A failure leaves a resumable intent, never a trial.
    try:
        sent = send_mail(
            "Potwierdź adres e-mail — Chatbot SaaS",
            "Aby założyć konto, otwórz poniższy link i ustaw własne hasło. "
            "Link jest jednorazowy i ważny 24 godziny. "
            "Nowa wiadomość unieważnia poprzedni link.\n\n"
            f"{url}\n\n"
            "Jeśli to nie Ty rozpoczynasz rejestrację, zignoruj wiadomość. "
            "Samo otwarcie linku nie zakłada konta.",
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )
        if sent != 1:
            raise EmailUnavailable()
    except Exception:
        # No SMTP response, address or token in public errors or application logs.
        raise EmailUnavailable() from None


def valid_pending(token, *, lock=False):
    query = PendingRegistration.objects
    if lock:
        query = query.select_for_update()
    pending = query.filter(token_digest=digest(token), used_at__isnull=True).first()
    now = timezone.now()
    if pending is None or pending.expires_at <= now or pending.created_at < now - timedelta(days=7):
        raise ValidationError({"token": INVALID})
    return pending
