from rest_framework.throttling import SimpleRateThrottle
from accounts.models import Tenant, Subscription

class APIKeyRateThrottle(SimpleRateThrottle):
    scope = "chat"

    def get_cache_key(self, request, view):
        api_key = request.headers.get("X-API-KEY")
        if not api_key:
            return None
        try:
            tenant = Tenant.objects.get(api_key=api_key)
            request.tenant = tenant  # <- udostępniamy tenant dalej
            subscription = (
                Subscription.objects
                .filter(tenant=tenant, is_active=True)
                .order_by("-end_date")
                .first()
            )
            request.subscription = subscription  # <- NAJWAŻNIEJSZE!
            return self.cache_format % {
                "scope": self.scope,
                "ident": f"tenant-{tenant.pk}"
            }
        except Tenant.DoesNotExist:
            return None

    def get_rate(self):
        subscription = getattr(self.request, "subscription", None)
        if subscription:
            plan = (subscription.plan_type or "free").lower()
        else:
            plan = "free"
        return {
            "free": "20/min",
            "pro": "100/min",
            "enterprise": "500/min",
        }.get(plan, "20/min")


class SubscriptionRateThrottle(SimpleRateThrottle):
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
        subscription = (
            Subscription.objects
            .filter(tenant=tenant, is_active=True)
            .order_by("-end_date")
            .first()
        )
        print("SET REQUEST.SUBSCRIPTION:", subscription)
        request.subscription = subscription
        return self.cache_format % {
            "scope": self.scope,
            "ident": f"tenant-{tenant.pk}"
        }

    def get_rate(self):
        subscription = getattr(self.request, "subscription", None)
        if subscription:
            plan = (subscription.plan_type or "free").lower()
        else:
            plan = "free"
        return {
            "free": "100/min",
            "pro": "1000/min",
            "enterprise": "20000/min",
        }.get(plan, "100/min")
