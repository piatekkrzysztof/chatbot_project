from django.utils.deprecation import MiddlewareMixin
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed
from accounts.models import Tenant


class TenantMiddleware(MiddlewareMixin):
    def process_request(self, request):
        tenant = None

        # JWT (użytkownik zalogowany)
        try:
            jwt_auth = JWTAuthentication()
            user_auth_tuple = jwt_auth.authenticate(request)
            if user_auth_tuple:
                user, _ = user_auth_tuple
                request.user = user
                tenant = getattr(user, 'tenant', None)
        except Exception:
            pass  # brak JWT = nie przerywamy

        # API Key fallback
        if not tenant:
            api_key = request.headers.get("X-API-Key")
            if api_key:
                try:
                    tenant = Tenant.objects.get(api_key=api_key)
                except Tenant.DoesNotExist:
                    raise AuthenticationFailed("Nieprawidłowy klucz API")

        if not tenant:
            raise AuthenticationFailed("Nie rozpoznano tenanta")

        request.tenant = tenant
