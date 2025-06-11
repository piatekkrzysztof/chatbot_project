from rest_framework.throttling import SimpleRateThrottle


class APIKeyRateThrottle(SimpleRateThrottle):
    scope = 'chat'

    def get_cache_key(self, request, view):
        api_key = request.headers.get('X-API-KEY')
        ident = api_key or self.get_ident(request)
        if not api_key:
            return None  # brak throttlingu (lub zablokuj całkiem)
        return self.cache_format % {
            'scope': self.scope,
            'ident': api_key
        }


from rest_framework.throttling import SimpleRateThrottle

class SubscriptionRateThrottle(SimpleRateThrottle):
    scope = 'subscription'

    def get_cache_key(self, request, view):
        if not request.user.is_authenticated:
            return None
        ident = request.user.id
        return self.cache_format % {
            'scope': self.scope,
            'ident': ident
        }

    def get_rate(self):
        user = self.request.user
        try:
            plan = user.tenant.subscription.plan_type.lower()
        except AttributeError:
            plan = 'free'

        return {
            'free': '20/min',
            'pro': '100/min',
            'enterprise': '500/min',
        }.get(plan, '20/min')