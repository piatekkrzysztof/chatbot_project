from django.utils.deprecation import MiddlewareMixin
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed
from accounts.models import Tenant
from django.http import JsonResponse
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from .models import Subscription


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


import time


class SubscriptionMiddleware(MiddlewareMixin):
    def process_request(self, request):

        if not request.path.startswith('/api/chat/'):
            return None

        api_key = request.headers.get('X-API-KEY')
        if not api_key:
            return JsonResponse(
                {'error': 'Missing API key'},
                status=401
            )

        try:
            subscription = Subscription.objects.select_related(
                'tenant'
            ).get(
                tenant__clients__api_key=api_key
            )
        except Subscription.DoesNotExist:
            return JsonResponse(
                {'error': 'Invalid subscription'},
                status=403
            )

        if not subscription.is_active:
            return JsonResponse(
                {'error': 'Subscription inactive'},
                status=403
            )

        current_month = timezone.now().month
        last_update_month = subscription.billing_cycle_start.month

        if current_month != last_update_month:
            subscription.reset_usage()

        if not subscription.has_message_quota():
            return JsonResponse(
                {
                    'error': 'Message limit exceeded',
                    'limit': subscription.message_limit,
                    'used': subscription.current_message_count
                },
                status=429
            )

        request.subscription = subscription
        return None
