import hashlib
import time

from django.conf import settings
from django.core.cache import cache as default_cache
from rest_framework.throttling import SimpleRateThrottle

from accounts.models import Tenant, Subscription
from accounts.plans import rate_for
from chat.privacy import client_ip


class BaseSubscriptionThrottle(SimpleRateThrottle):
    """
    Bazowa klasa dla throttle'ów opartych o subskrypcję
    """

    def __init__(self):
        # Pomijamy inicjalizację rate do czasu dostępności requestu
        self.rate = None
        self.num_requests = None
        self.duration = None

    def _subskrypcja(self):
        """
        Subskrypcja żądania — z middleware albo dociągnięta z bazy.

        SubscriptionMiddleware ustawia ją wyłącznie na trzech ścieżkach czatu.
        Na całej reszcie panelu było więc pusto i throttle brał plan "free",
        czyli klient planu Pro chodził po panelu na stawce darmowej. Limit
        z cennika obowiązywał tylko tam, gdzie akurat przeszedł middleware.

        Wynik zapisujemy na żądaniu, bo get_cache_key obu klas throttle robi
        dokładnie to samo zapytanie — w sumie wychodzi ich mniej, nie więcej.
        """
        subskrypcja = getattr(self.request, "subscription", None)
        if subskrypcja is not None:
            return subskrypcja

        tenant = getattr(self.request, "tenant", None)
        if tenant is None:
            return None

        subskrypcja = (
            Subscription.objects.filter(tenant=tenant, is_active=True).order_by("-end_date").first()
        )
        self.request.subscription = subskrypcja
        return subskrypcja

    def get_rate(self):
        """Dynamicznie ustala rate na podstawie requestu"""
        if not hasattr(self, "request"):
            return "100/min"  # Domyślny limit bezpieczeństwa

        subscription = self._subskrypcja()
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
            self.rate = rate

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
                Subscription.objects.filter(tenant=tenant, is_active=True)
                .order_by("-end_date")
                .first()
            )
            request.subscription = subscription
            return self.cache_format % {"scope": self.scope, "ident": f"tenant-{tenant.pk}"}
        except Tenant.DoesNotExist:
            return None

    def get_plan_rate(self, plan):
        # Stawki pochodzą z katalogu planów — patrz accounts/plans.py
        return rate_for(plan)


class VisitorRateThrottle(SimpleRateThrottle):
    """
    Limit na pojedynczego odwiedzającego stronę klienta.

    Limity per tenant chronią nas przed klientem, ale nie chronią klienta przed
    jednym natrętnym rozmówcą: bez tego ktoś siedzący na stronie salonu mógł sam
    wyczerpać cały miesięczny pakiet, za który klient zapłacił.

    Klucz łączy firmę z adresem odwiedzającego — ten sam adres na dwóch różnych
    stronach to dwa niezależne liczniki, bo limity należą do klientów, nie do nas.
    """

    scope = "visitor"

    def get_rate(self):
        return getattr(settings, "LIMIT_ODWIEDZAJACEGO", "20/hour")

    def get_cache_key(self, request, view):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            # Bez rozpoznanej firmy żądanie i tak zostanie odrzucone wyżej
            return None

        adres = client_ip(request)
        if not adres:
            # Nie potrafimy odróżnić odwiedzającego — wpuszczamy. Limit, który
            # przy niepewności blokuje, zablokowałby wszystkich naraz.
            return None

        # W kluczu cache trzymamy skrót, nie sam adres: to dane osobowe, a do
        # zliczania wystarczy wartość stała dla danego odwiedzającego.
        odcisk = hashlib.sha256(f"{settings.SECRET_KEY}:{tenant.pk}:{adres}".encode()).hexdigest()[
            :32
        ]

        return self.cache_format % {"scope": self.scope, "ident": odcisk}


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
            Subscription.objects.filter(tenant=tenant, is_active=True).order_by("-end_date").first()
        )
        request.subscription = subscription
        return self.cache_format % {"scope": self.scope, "ident": f"tenant-{tenant.pk}"}

    def get_plan_rate(self, plan):
        """
        Limit dla ruchu panelu, luźniejszy niż czatu: jedno otwarcie strony
        to kilka żądań, a właściciel klikający po panelu nie może się o nie
        obijać. Skala bierze się z tego samego katalogu, żeby stawki nie
        rozjechały się z cennikiem.
        """
        na_minute = int(rate_for(plan).split("/")[0])
        return f"{na_minute * 10}/min"
