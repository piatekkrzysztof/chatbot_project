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
