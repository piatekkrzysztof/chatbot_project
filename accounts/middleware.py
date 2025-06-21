from django.utils.deprecation import MiddlewareMixin
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed
from accounts.models import Tenant
from django.http import JsonResponse
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from .models import Subscription
from dateutil.relativedelta import relativedelta


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

    def get_active_subscription(self, tenant):
        today = timezone.now().date()
        print(f"Checking subscription for tenant {tenant.name} on {today}")

        try:
            subscription = Subscription.objects.get(
                tenant=tenant,
                is_active=True,
                start_date__lte=today,
                end_date__gte=today
            )
            print(f"Active subscription found: {subscription.id} "
                  f"({subscription.start_date} to {subscription.end_date})")
            return subscription
        except Subscription.DoesNotExist:
            print("No active subscription found")
            return None
        except Subscription.MultipleObjectsReturned:
            print("Multiple active subscriptions found! Using first")
            return Subscription.objects.filter(
                tenant=tenant,
                is_active=True,
                start_date__lte=today,
                end_date__gte=today
            ).first()


import time


class SubscriptionMiddleware(MiddlewareMixin):
    def process_request(self, request):
        # Obsługujemy tylko endpoint /api/chat/
        if not request.path.startswith('/api/chat/'):
            return None

        api_key = request.headers.get('X-API-KEY')
        if not api_key:
            return JsonResponse({'error': 'Missing API key'}, status=401)

        try:
            # 1. Znajdź Tenant po kluczu API
            tenant = Tenant.objects.get(api_key=api_key)

            # 2. Pobierz subskrypcję powiązaną z tenantem
            try:
                subscription = Subscription.objects.get(tenant=tenant)
            except Subscription.DoesNotExist:
                return JsonResponse({'error': 'Subscription not found'}, status=403)
            except Subscription.MultipleObjectsReturned:
                # Logika awaryjna - wybierz pierwszą aktywną subskrypcję
                subscription = Subscription.objects.filter(
                    tenant=tenant,
                    is_active=True
                ).order_by('-end_date').first()
                if not subscription:
                    return JsonResponse({'error': 'No active subscription'}, status=403)

            # 3. Sprawdź daty ważności subskrypcji
            today = timezone.now().date()
            if not (subscription.is_active and
                    subscription.start_date <= today <= subscription.end_date):
                return JsonResponse({'error': 'Subscription expired'}, status=403)

            # 4. Sprawdź czy cykl rozliczeniowy wymaga resetu
            # Bezpieczne sprawdzenie czy minął miesiąc (uwzględnia lata)
            next_billing_date = subscription.billing_cycle_start + relativedelta(months=1)
            if today >= next_billing_date:
                subscription.reset_usage()

            # 5. Sprawdź limit wiadomości
            if not subscription.has_message_quota():
                return JsonResponse(
                    {
                        'error': 'Message limit exceeded',
                        'limit': subscription.message_limit,
                        'used': subscription.current_message_count
                    },
                    status=429
                )

            # 6. Przypisz subskrypcję do requestu
            request.subscription = subscription
            return None

        except Tenant.DoesNotExist:
            return JsonResponse({'error': 'Invalid API key'}, status=401)
