import logging

from django.utils.deprecation import MiddlewareMixin
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed, APIException
from accounts.models import Tenant
from django.http import JsonResponse
from django.utils import timezone
from .models import Subscription
from dateutil.relativedelta import relativedelta

logger = logging.getLogger(__name__)


class TenantMiddleware:
    """
    Middleware wymuszający obecność tenanta dla każdego requestu API,
    poza ścieżkami rejestracji i logowania.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def process_request(self, request):
        # Middleware dotyczy tylko API — /admin/, statyki itd. mają własną autoryzację.
        if not request.path.startswith("/api/"):
            return

        # Ścieżki dostępne zanim ktokolwiek ma konto lub klucz API.
        exempt_paths = [
            "/api/accounts/register/",
            "/api/accounts/login/",
            # Odswiezanie i wylogowanie z definicji dzialaja bez waznego
            # tokenu dostepu -- to jest ich caly sens. Tozsamosc potwierdza
            # tu token odswiezania z ciasteczka HttpOnly, sprawdzany w widoku.
            # Bez tego wyjatku wygasla sesja nie dawala sie odnowic ani
            # zakonczyc: uzytkownik zostawal z martwym panelem.
            "/api/accounts/token/refresh/",
            "/api/accounts/logout/",
            # Zapraszany dopiero zakłada konto — nie ma jeszcze ani tokenu JWT,
            # ani klucza API, więc bez tego wyjątku każde zaproszenie kończyło
            # się odmową "Nie rozpoznano tenanta".
            "/api/accounts/accept-invite/",
            # Stripe woła nas z własnych serwerów: nie ma tokenu ani klucza API.
            # Tożsamość potwierdza podpis zdarzenia, sprawdzany w samym widoku.
            "/api/billing/webhook/",
            # Cennik czyta strona sprzedażowa, zanim ktokolwiek założy konto —
            # z definicji nie ma jeszcze ani tenanta, ani klucza API.
            "/api/billing/cennik/",
        ]
        if request.path in exempt_paths:
            return

        # Podgląd zaproszenia ma token w adresie, więc nie da się go dopasować
        # dokładnie; sam token jest tu jednocześnie danymi uwierzytelniającymi.
        if request.path.startswith("/api/accounts/invitations/") and request.path.endswith(
            "/preview/"
        ):
            return

        tenant = None

        # 1. Jeśli user jest już zalogowany (force_authenticate albo login przez DRF/JWT)
        if hasattr(request, "user") and getattr(request.user, "is_authenticated", False):
            tenant = getattr(request.user, "tenant", None)
            if tenant:
                request.tenant = tenant

        # 2. Jeśli nie user, to JWT
        if not tenant:
            try:
                jwt_auth = JWTAuthentication()
                user_auth_tuple = jwt_auth.authenticate(request)
                if user_auth_tuple:
                    user, _ = user_auth_tuple
                    request.user = user
                    tenant = getattr(user, "tenant", None)
            except Exception:
                pass

        # 3. Jeśli nie user, nie JWT, to spróbuj po API Key
        if not tenant:
            api_key = request.headers.get("X-API-Key")
            if api_key:
                try:
                    tenant = Tenant.objects.get(api_key=api_key)
                except Tenant.DoesNotExist:
                    raise AuthenticationFailed("Nieprawidłowy klucz API")

        # 4. Ostatecznie, jeśli nadal brak tenant – blokuj request
        if not tenant:
            raise AuthenticationFailed("Nie rozpoznano tenanta")

        request.tenant = tenant

    def __call__(self, request):
        try:
            self.process_request(request)
        except APIException as exc:
            return JsonResponse({"detail": str(exc.detail)}, status=exc.status_code)
        response = self.get_response(request)
        return response

    def get_active_subscription(self, tenant):

        today = timezone.now().date()

        try:
            subscription = Subscription.objects.get(
                tenant=tenant, is_active=True, start_date__lte=today, end_date__gte=today
            )
            return subscription
        except Subscription.DoesNotExist:
            return None
        except Subscription.MultipleObjectsReturned:
            return Subscription.objects.filter(
                tenant=tenant, is_active=True, start_date__lte=today, end_date__gte=today
            ).first()


import time


#: Kod odmowy dla widgetu.
#:
#: Wszystkie powody, dla ktorych czat jest niedostepny -- wygasla subskrypcja,
#: brak subskrypcji, wyczerpany limit wiadomosci -- znacza dla odwiedzajacego
#: dokladnie to samo: teraz nie odpowiemy i ponawianie nic nie da. Widget
#: pokazuje wtedy uczciwy komunikat zamiast "Wystapil blad, sprobuj ponownie",
#: ktory kaze powtarzac cos, co nigdy nie zadziala.
#:
#: Jeden kod, a nie osobny dla kazdego powodu, celowo: rozliczenia klienta nie
#: sa sprawa jego odwiedzajacych. Wlasciciel dowiaduje sie o przyczynie
#: mailem i w panelu.
KOD_CZAT_NIEDOSTEPNY = "czat_niedostepny"


class SubscriptionMiddleware(MiddlewareMixin):
    # Dokładne ścieżki (nie prefiksy!) — endpointy wysyłające wiadomość do AI.
    # Prefiksowe dopasowanie złapałoby też /api/chat/logs/, /api/chat/feedback/ itd.,
    # które są JWT-owymi endpointami panelu, nie publicznym czatem po X-API-Key.
    CHAT_PATHS = ("/api/chat/", "/api/widget/chat/", "/api/widget/chat/stream/")

    def process_request(self, request):
        # Obsługujemy tylko endpointy czatu (panel + publiczny widget)
        if request.path not in self.CHAT_PATHS:
            return None

        api_key = request.headers.get("X-API-KEY")
        if not api_key:
            return JsonResponse({"error": "Missing API key"}, status=401)

        try:
            # 1. Znajdź Tenant po kluczu API
            tenant = Tenant.objects.get(api_key=api_key)

            # 2. Pobierz subskrypcję powiązaną z tenantem
            try:
                subscription = Subscription.objects.get(tenant=tenant)
            except Subscription.DoesNotExist:
                return JsonResponse(
                    {"error": "Subscription not found", "kod": KOD_CZAT_NIEDOSTEPNY},
                    status=403,
                )
            except Subscription.MultipleObjectsReturned:
                # Logika awaryjna - wybierz pierwszą aktywną subskrypcję
                subscription = (
                    Subscription.objects.filter(tenant=tenant, is_active=True)
                    .order_by("-end_date")
                    .first()
                )
                if not subscription:
                    return JsonResponse(
                        {"error": "No active subscription", "kod": KOD_CZAT_NIEDOSTEPNY},
                        status=403,
                    )

            # 3. Sprawdź daty ważności subskrypcji
            today = timezone.now().date()
            if not (
                subscription.is_active and subscription.start_date <= today <= subscription.end_date
            ):
                return JsonResponse(
                    {"error": "Subscription expired", "kod": KOD_CZAT_NIEDOSTEPNY},
                    status=403,
                )

            # 4. Sprawdź czy cykl rozliczeniowy wymaga resetu
            # Bezpieczne sprawdzenie czy minął miesiąc (uwzględnia lata)
            next_billing_date = subscription.billing_cycle_start + relativedelta(months=1)
            if today >= next_billing_date:
                subscription.reset_usage()

            # 5. Sprawdź limit wiadomości
            if not subscription.has_message_quota():
                return JsonResponse(
                    {
                        "error": "Message limit exceeded",
                        "kod": KOD_CZAT_NIEDOSTEPNY,
                        "limit": subscription.message_limit,
                        "used": subscription.current_message_count,
                    },
                    status=429,
                )

            # 6. Przypisz subskrypcję do requestu
            request.subscription = subscription
            return None

        except Tenant.DoesNotExist:
            return JsonResponse({"error": "Invalid API key"}, status=401)


#: Ścieżki, których nie zapisujemy.
#:
#: Ruch widgetu to zwykli odwiedzający strony klienta, a nie działania w
#: panelu - zapisywanie ich zamieniłoby dziennik w log dostępu i utopiło w nim
#: to, po co powstał. Webhook Stripe'a przychodzi z zewnątrz i ma własny ślad
#: po stronie Stripe'a.
SCIEZKI_POZA_DZIENNIKIEM = ("/api/widget/", "/api/billing/webhook/")


class DziennikAudytuMiddleware(MiddlewareMixin):
    """
    Zapisuje każde żądanie zmieniające dane.

    Automatycznie, a nie przez wywołania rozsiane po widokach - bo o wywołanie
    da się zapomnieć przy dopisywaniu nowej końcówki, a wtedy dziennik jest
    pełny, wygląda na kompletny i akurat tej jednej rzeczy nie zawiera. Tutaj
    nowa końcówka trafia do dziennika sama.

    Zapis w `process_response`, nie w `process_request`: przed widokiem nie
    wiadomo jeszcze ani kto to jest, ani jak się skończyło. DRF uwierzytelnia
    dopiero w widoku i ustawia użytkownika także na żądaniu Django, więc po
    odpowiedzi jedno i drugie jest już znane.
    """

    METODY_ZMIENIAJACE = {"POST", "PUT", "PATCH", "DELETE"}

    def process_response(self, request, response):
        if request.method not in self.METODY_ZMIENIAJACE:
            return response
        if not request.path.startswith("/api/"):
            return response
        if request.path.startswith(SCIEZKI_POZA_DZIENNIKIEM):
            return response

        from accounts.models import WpisDziennika
        from chat.privacy import client_ip

        uzytkownik = getattr(request, "user", None)
        if not getattr(uzytkownik, "is_authenticated", False):
            uzytkownik = None

        try:
            WpisDziennika.objects.create(
                tenant=getattr(request, "tenant", None),
                uzytkownik=uzytkownik,
                nazwa_uzytkownika=getattr(uzytkownik, "username", "") or "",
                metoda=request.method,
                sciezka=request.path[:255],
                status=response.status_code,
                adres_ip=client_ip(request) or "",
            )
        except Exception:
            # Dziennik nie może wywrócić żądania, które już się powiodło.
            # Zapisana zmiana bez wpisu to luka w dzienniku; odrzucone żądanie
            # z powodu awarii dziennika to utrata pracy użytkownika. Z dwojga
            # złego wybieramy lukę - i zostawiamy po niej ślad w logu.
            logger.exception("Nie udalo sie zapisac wpisu dziennika audytowego")

        return response
