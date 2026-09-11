"""Atomic fixed-window limits for account creation, independent of a tenant."""

import math
import time

from django.conf import settings
from django.core.cache import cache
from django.utils.crypto import salted_hmac
from rest_framework.exceptions import APIException
from rest_framework.throttling import BaseThrottle

from chat.privacy import client_ip


class RegistrationUnavailable(APIException):
    status_code = 503
    default_detail = "Zakładanie kont jest chwilowo niedostępne. Spróbuj za chwilę."
    default_code = "registration_unavailable"


class RegistrationThrottle(BaseThrottle):
    scope = "registration"
    ip_limit = 5
    window = 3600
    global_limit = 30

    def allow_request(self, request, view):
        if getattr(settings, "USE_SHARED_CACHE", True) is False:
            raise RegistrationUnavailable()
        now = time.time()
        ident = salted_hmac("account-rate", str(client_ip(request) or "unknown")).hexdigest()
        self.remaining = 0
        for identity, limit, window in (
            (ident, self.ip_limit, self.window),
            ("global", self.global_limit, 60),
        ):
            key = f"account-rate:{self.scope}:{identity}:{int(now // window)}"
            try:
                if cache.add(key, 1, timeout=window + 1):
                    count = 1
                else:
                    count = cache.incr(key)
            except Exception:
                # An unavailable shared counter must not enable unbounded signups.
                raise RegistrationUnavailable() from None
            if count > limit:
                self.remaining = max(1, math.ceil(window - now % window))
                return False
        return True

    def wait(self):
        return self.remaining


class InvitationAcceptThrottle(RegistrationThrottle):
    scope = "invitation-accept"
    ip_limit = 20
    global_limit = 60


class InvitationPreviewThrottle(RegistrationThrottle):
    scope = "invitation-preview"
    ip_limit = 60
    window = 60
    global_limit = 300
