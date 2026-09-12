from django.core.cache import cache
from django.utils.crypto import salted_hmac

from api.registration_throttles import RegistrationThrottle, RegistrationUnavailable


class RecoveryUnavailable(RegistrationUnavailable):
    default_detail = "Odzyskiwanie hasła jest chwilowo niedostępne. Spróbuj za chwilę."
    default_code = "password_recovery_unavailable"


class PasswordRequestThrottle(RegistrationThrottle):
    scope = "password-reset-request"
    ip_limit = 10
    global_limit = 30

    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except RegistrationUnavailable:
            raise RecoveryUnavailable() from None


class PasswordConfirmThrottle(PasswordRequestThrottle):
    scope = "password-reset-confirm"
    ip_limit = 30
    window = 300
    global_limit = 120


def allow_email(email):
    """Same counters for registered and unknown addresses; no existence oracle."""
    key = "password-reset-email:" + salted_hmac("password-reset-limit", email).hexdigest()
    try:
        if not cache.add(key + ":minute", 1, timeout=60):
            return False
        count = 1 if cache.add(key + ":day", 1, timeout=86400) else cache.incr(key + ":day")
    except Exception:
        raise RecoveryUnavailable() from None
    return count <= 5
