from rest_framework.throttling import SimpleRateThrottle
from accounts.models import Tenant, Subscription
from django.core.cache import cache as default_cache
import time


class BaseSubscriptionThrottle(SimpleRateThrottle):
    """
    Bazowa klasa dla throttle'ów opartych o subskrypcję
    """

    def __init__(self):
        # Pomijamy inicjalizację rate do czasu dostępności requestu
        self.rate = None
        self.num_requests = None
        self.duration = None

    def get_rate(self):
        """Dynamicznie ustala rate na podstawie requestu"""
        if not hasattr(self, 'request'):
            return "100/min"  # Domyślny limit bezpieczeństwa

        subscription = getattr(self.request, "subscription", None)
        if subscription:
            plan = (subscription.plan_type or "free").lower()
        else:
            plan = "free"

        return self.get_plan_rate(plan)

    def get_plan_rate(self, plan):
        """Mapowanie planów na limity (do nadpisania w klasach potomnych)"""
        raise NotImplementedError("Subclasses must implement this method")

    def allow_request(self, request, view):
        # Ustaw request przed sprawdzeniem limitu
        self.request = request

        # Ustaw rate dynamicznie
        rate = self.get_rate()
        if rate:
            self.num_requests, self.duration = self.parse_rate(rate)

        return super().allow_request(request, view)


class APIKeyRateThrottle(BaseSubscriptionThrottle):
    scope = "chat"

    def get_cache_key(self, request, view):
        api_key = request.headers.get("X-API-KEY")
        if not api_key:
            return None

        try:
            tenant = Tenant.objects.get(api_key=api_key)
            request.tenant = tenant

            # Pobierz aktywną subskrypcję (jeśli istnieje)
            subscription = (
                Subscription.objects
                .filter(tenant=tenant, is_active=True)
                .order_by("-end_date")
                .first()
            )
            request.subscription = subscription
            return self.cache_format % {
                "scope": self.scope,
                "ident": f"tenant-{tenant.pk}"
            }
        except Tenant.DoesNotExist:
            return None

    def get_plan_rate(self, plan):
        return {
            "free": "20/min",
            "pro": "100/min",
            "enterprise": "500/min",
        }.get(plan, "20/min")


class SubscriptionRateThrottle(BaseSubscriptionThrottle):
    scope = "subscription"

    def get_cache_key(self, request, view):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            api_key = request.headers.get("X-API-KEY")
            if not api_key:
                return None

            try:
                tenant = Tenant.objects.get(api_key=api_key)
                request.tenant = tenant
            except Tenant.DoesNotExist:
                return None

        # Pobierz aktywną subskrypcję
        subscription = (
            Subscription.objects
            .filter(tenant=tenant, is_active=True)
            .order_by("-end_date")
            .first()
        )
        request.subscription = subscription
        return self.cache_format % {
            "scope": self.scope,
            "ident": f"tenant-{tenant.pk}"
        }

    def get_plan_rate(self, plan):
        return {
            "free": "100/min",
            "pro": "1000/min",
            "enterprise": "20000/min",
        }.get(plan, "100/min")