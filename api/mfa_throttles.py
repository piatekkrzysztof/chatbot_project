from django.core.cache import cache
from django.utils.crypto import salted_hmac
from rest_framework.exceptions import Throttled

from api.registration_throttles import RegistrationThrottle, RegistrationUnavailable


class MfaUnavailable(RegistrationUnavailable):
    default_detail = "Weryfikacja MFA jest chwilowo niedostępna. Spróbuj za chwilę."
    default_code = "mfa_unavailable"


class MfaThrottle(RegistrationThrottle):
    scope = "mfa"
    ip_limit = 30
    window = 300
    global_limit = 120

    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except RegistrationUnavailable:
            raise MfaUnavailable() from None


def account_attempt(user):
    key = "mfa-account:" + salted_hmac("mfa-limit", str(user.pk)).hexdigest()
    try:
        count = 1 if cache.add(key, 1, timeout=300) else cache.incr(key)
    except Exception:
        raise MfaUnavailable() from None
    if count > 10:
        raise Throttled(wait=300)
