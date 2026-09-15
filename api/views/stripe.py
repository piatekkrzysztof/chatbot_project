import logging
import re
import time

import stripe
from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Subscription
from accounts.plans import (
    BRANDING_WLASNY,
    PAKIET_CENA_PLN,
    PAKIET_WIADOMOSCI,
    PLANS,
    get_plan,
)
from api.permissions import IsOwner
from api.schemas import (
    BillingOverviewSerializer,
    CheckoutRequestSerializer,
    CheckoutResponseSerializer,
    CheckoutStatusSerializer,
    ErrorSerializer,
    PortalRequestSerializer,
    PortalResponseSerializer,
    PublicPricingSerializer,
)
from api.utils.stripe_klient import kartoteka_klienta
from api.utils.stripe_portal import konfiguracja_portalu, zapomnij_konfiguracje
from api.views.stripe_webhook import (
    STATUSY_Z_DOSTEPEM,
    ZdarzenieDoPonowienia,
    _identyfikator,
    pobierz_subskrypcje,
    synchronizuj_subskrypcje,
)

logger = logging.getLogger(__name__)

#: Okno, w którym ponowne wejście do płatności za ten sam plan zwraca TĘ SAMĄ
#: sesję Stripe. Podwójne kliknięcie albo dwie karty z panelem dawały wcześniej
#: dwie niezależne sesje - każdą dało się opłacić osobno.
OKNO_IDEMPOTENCJI_SEKUND = 600

#: Identyfikator sesji Checkout. Sprawdzany przed wywołaniem Stripe, żeby adres
#: strony sukcesu nie był furtką do dowolnych zapytań w naszym imieniu.
WZOR_SESJI = re.compile(r"^cs_(test|live)_[A-Za-z0-9]{8,200}$")

PLATNOSC_ZAKONCZONA = frozenset({"paid", "no_payment_required"})

NIE_ZNALEZIONO_PLATNOSCI = "Nie znaleźliśmy tej płatności na Twoim koncie."


class BladPlatnosci(ValidationError):
    """
    Odmowa z jednym zdaniem dla klienta: `{"detail": "..."}`.

    Zwykły ValidationError z samym napisem DRF zamienia w listę, więc panel
    pokazywał klientowi dosłownie `["Masz już aktywną subskrypcję..."]`.
    Dziedziczy po ValidationError, żeby miejsca, które go łapią, działały
    bez zmian.
    """

    def __init__(self, komunikat):
        APIException.__init__(self, komunikat)


class PlatnosciNiedostepne(APIException):
    """Stripe chwilowo nie odpowiada - panel ma spróbować ponownie, nie ogłaszać porażki."""

    status_code = 503
    default_detail = "Nie możemy teraz sprawdzić płatności w Stripe. Spróbuj ponownie za chwilę."
    default_code = "platnosci_niedostepne"


def aktywna_subskrypcja_stripe(tenant):
    """Subskrypcja firmy opłacana przez Stripe i dająca dostęp - albo None."""
    obecna = Subscription.objects.filter(tenant=tenant).first()
    if (
        obecna
        and obecna.stripe_subscription_id
        and obecna.is_active
        and obecna.stripe_status in STATUSY_Z_DOSTEPEM
    ):
        return obecna
    return None


def create_checkout_session(tenant, plan_code, email=None):
    """
    Sesja płatności Stripe dla wybranego planu.

    Wcześniej istniały dwie równoległe implementacje: ta z zaszytym w kodzie
    słownikiem zastępczych price_id oraz druga w api/utils/stripe.py, biorąca
    jeden identyfikator ze zmiennej dla wszystkich planów. Rejestracja szła
    przez jedną, panel przez drugą, więc kupiony plan zależał od tego, którędy
    klient przyszedł.

    tenant_id w metadanych jest jedynym wiązaniem płatności z firmą — webhook
    nie ma po czym jej rozpoznać, jeśli go zabraknie.
    """
    plan = get_plan(plan_code)
    if plan is None:
        raise BladPlatnosci(f"Nieznany plan: {plan_code}. Dostępne: {', '.join(PLANS)}.")

    price_id = settings.STRIPE_PRICE_IDS.get(plan.code)
    if not price_id:
        logger.error("Brak identyfikatora ceny Stripe dla planu %s", plan.code)
        raise BladPlatnosci(
            f"Plan {plan.name} nie jest jeszcze dostępny do zakupu. Skontaktuj się z nami."
        )

    # Drugi zakup przy aktywnej subskrypcji zakładał w Stripe DRUGĄ subskrypcję:
    # dwa obciążenia co miesiąc za jedno konto. Plan zmienia się w portalu, na
    # tej samej subskrypcji (otworz_portal).
    obecna = aktywna_subskrypcja_stripe(tenant)
    if obecna:
        obecny_plan = get_plan(obecna.plan_type)
        raise BladPlatnosci(
            f"Masz już aktywną subskrypcję "
            f"({obecny_plan.name if obecny_plan else obecna.plan_type}). Plan zmienisz "
            "przyciskiem przy wybranym planie w zakładce Subskrypcja - bez drugiej "
            "subskrypcji i podwójnej opłaty."
        )

    stripe.api_key = settings.STRIPE_SECRET_KEY
    frontend = settings.FRONTEND_URL.rstrip("/")

    try:
        session = _utworz_sesje(stripe, tenant, plan, price_id, email, frontend)
    except stripe.error.StripeError as blad:
        # Bez tego każdy problem po stronie Stripe (zła cena, wygasły klucz,
        # niedostępność API) wychodził jako 500 z pustym komunikatem, a panel
        # pokazywał puste miejsce zamiast wyjaśnienia. Prawdziwy powód szedł
        # wyłącznie do logu, o ile ktoś wiedział, gdzie patrzeć.
        #
        # Najczęstszy przypadek przy konfiguracji: identyfikator ceny
        # z trybu produkcyjnego przy kluczu testowym albo odwrotnie.
        logger.exception("Stripe odmówił utworzenia sesji dla planu %s", plan.code)
        raise BladPlatnosci(
            "Nie udało się rozpocząć płatności. Spróbuj ponownie za chwilę, "
            "a jeśli problem się powtórzy — daj nam znać."
        ) from blad
    return session.url


def _utworz_sesje(stripe, tenant, plan, price_id, email, frontend):
    """Samo wywołanie Stripe, wydzielone, żeby obsługa błędu była czytelna."""
    # Kartoteka klienta niesie nazwe, adres i NIP - czyli to, co musi znalezc
    # sie na fakturze. Bez niej Stripe zaklada nowa, anonimowa przy kazdym
    # zakupie, a polska firma dostaje dokument bez wlasnego NIP-u.
    identyfikator = kartoteka_klienta(tenant, email)

    # Droga awaryjna: gdy Stripe odmowil obslugi kartoteki, platnosc idzie
    # dalej po samym adresie e-mail. Faktura bez pelnych danych jest klopotem,
    # ale klient, ktory nie moze zaplacic, jest klopotem wiekszym i naszym.
    rozpoznanie = (
        {"customer": identyfikator}
        if identyfikator
        else {"customer_email": email or tenant.owner_email}
    )

    okno = int(time.time() // OKNO_IDEMPOTENCJI_SEKUND)
    kto = rozpoznanie.get("customer") or rozpoznanie.get("customer_email") or ""

    return stripe.checkout.Session.create(
        idempotency_key=f"checkout-{tenant.id}-{plan.code}-{price_id}-{kto}-{okno}",
        mode="subscription",
        **rozpoznanie,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{frontend}/platnosc/sukces?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{frontend}/platnosc/anulowano",
        metadata={"tenant_id": str(tenant.id), "plan": plan.code},
        # Metadane sesji nie przechodzą na subskrypcję, a zdarzenia odnowienia
        # dotyczą właśnie subskrypcji — bez tego nie da się ich powiązać z firmą
        subscription_data={"metadata": {"tenant_id": str(tenant.id), "plan": plan.code}},
    )


def otworz_portal(tenant, plan_code=None):
    """
    Adres portalu klienta Stripe dla firmy.

    Z planem - od razu ekran potwierdzenia zmiany na tej samej subskrypcji,
    z wyliczoną przez Stripe dopłatą albo datą, od której obowiązuje niższy
    plan. Bez planu - strona główna portalu: karta, faktury, anulowanie.
    """
    if not tenant.stripe_customer_id:
        raise BladPlatnosci(
            "Nie masz jeszcze subskrypcji opłacanej przez Stripe. Wybierz plan, żeby ją założyć."
        )

    stripe.api_key = settings.STRIPE_SECRET_KEY
    frontend = settings.FRONTEND_URL.rstrip("/")
    parametry = {
        "customer": tenant.stripe_customer_id,
        "return_url": f"{frontend}/subskrypcja",
        "locale": "pl",
    }

    try:
        if plan_code:
            parametry["flow_data"] = _zmiana_planu(tenant, plan_code, frontend)
        parametry["configuration"] = konfiguracja_portalu()
        sesja = stripe.billing_portal.Session.create(**parametry)
    except stripe.error.StripeError as blad:
        zapomnij_konfiguracje()
        logger.exception("Stripe odmówił otwarcia portalu dla firmy %s", tenant.id)
        raise BladPlatnosci(
            "Nie udało się otworzyć zarządzania subskrypcją. Spróbuj ponownie za chwilę, "
            "a jeśli problem się powtórzy - daj nam znać."
        ) from blad
    return sesja.url


def _zmiana_planu(tenant, plan_code, frontend):
    """Przebieg portalu prowadzący prosto do potwierdzenia zmiany planu."""
    plan = get_plan(plan_code)
    if plan is None:
        raise BladPlatnosci(f"Nieznany plan: {plan_code}. Dostępne: {', '.join(PLANS)}.")

    cena = settings.STRIPE_PRICE_IDS.get(plan.code)
    if not cena:
        raise BladPlatnosci(f"Plan {plan.name} nie jest jeszcze dostępny. Skontaktuj się z nami.")

    obecna = aktywna_subskrypcja_stripe(tenant)
    if obecna is None:
        raise BladPlatnosci(
            "Zmiana planu dotyczy opłacanej subskrypcji. Wybierz plan, żeby ją założyć."
        )

    subskrypcja = stripe.Subscription.retrieve(obecna.stripe_subscription_id)
    pozycje = (subskrypcja.get("items") or {}).get("data") or []
    if len(pozycje) != 1:
        # Plan to jedna pozycja subskrypcji. Inny układ ktoś ustawił ręcznie
        # w Stripe i zamiana ceny jednej z pozycji zrobiłaby nie wiadomo co.
        logger.error(
            "Subskrypcja %s firmy %s ma %s pozycji - zmiana planu z panelu wstrzymana",
            obecna.stripe_subscription_id,
            tenant.id,
            len(pozycje),
        )
        raise BladPlatnosci(
            "Tej subskrypcji nie da się zmienić z panelu. Napisz do nas, zmienimy ją ręcznie."
        )

    pozycja = pozycje[0]
    if _identyfikator(pozycja.get("price")) == cena:
        raise BladPlatnosci(f"{plan.name} to Twój obecny plan.")

    return {
        "type": "subscription_update_confirm",
        "subscription_update_confirm": {
            "subscription": subskrypcja["id"],
            "items": [{"id": pozycja["id"], "price": cena, "quantity": 1}],
        },
        "after_completion": {
            "type": "redirect",
            "redirect": {"return_url": f"{frontend}/subskrypcja?zmiana=1"},
        },
    }


def stan_zakupu(tenant, identyfikator_sesji):
    """
    Czy KONKRETNA płatność z Checkout dała firmie dostęp.

    Strona sukcesu sprawdzała dotąd ogólny stan planu. Firma z aktywnym okresem
    próbnym widziała więc „plan aktywny", zanim cokolwiek się stało, a przy
    spóźnionym webhooku klient z pobraną płatnością czekał bez końca.

    Gdy płatność jest zakończona, a webhook jeszcze nie dotarł, uzgadniamy stan
    sami - tą samą drogą co webhook: bieżąca subskrypcja ze Stripe, zapis pod
    blokadą wiersza firmy. Webhook, który dojdzie później, zapisze to samo.
    """
    if not WZOR_SESJI.match(identyfikator_sesji or ""):
        raise NotFound(NIE_ZNALEZIONO_PLATNOSCI)

    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        sesja = stripe.checkout.Session.retrieve(identyfikator_sesji)
    except stripe.error.InvalidRequestError as blad:
        raise NotFound(NIE_ZNALEZIONO_PLATNOSCI) from blad
    except stripe.error.StripeError as blad:
        raise PlatnosciNiedostepne() from blad

    metadane = sesja.get("metadata") or {}
    if str(metadane.get("tenant_id") or "") != str(tenant.id):
        # Cudza sesja wygląda tak samo jak nieistniejąca: identyfikator nie
        # może służyć do sprawdzania, czy inna firma coś kupiła.
        raise NotFound(NIE_ZNALEZIONO_PLATNOSCI)

    plan = get_plan(metadane.get("plan"))
    wynik = {
        "status": "w_toku",
        "plan": metadane.get("plan"),
        "plan_name": plan.name if plan else metadane.get("plan"),
        "access_until": None,
    }

    if sesja.get("status") == "expired":
        return {**wynik, "status": "wygasla"}

    sid = _identyfikator(sesja.get("subscription"))
    if (
        sesja.get("status") != "complete"
        or sesja.get("payment_status") not in PLATNOSC_ZAKONCZONA
        or not sid
    ):
        return wynik

    powiazana = Subscription.objects.filter(tenant=tenant, stripe_subscription_id=sid).first()
    if not (powiazana and powiazana.is_active):
        try:
            subskrypcja = pobierz_subskrypcje(sid)
        except ZdarzenieDoPonowienia as blad:
            raise PlatnosciNiedostepne() from blad
        if subskrypcja is not None:
            synchronizuj_subskrypcje(tenant, subskrypcja)
            powiazana = Subscription.objects.filter(
                tenant=tenant, stripe_subscription_id=sid
            ).first()
            if powiazana and powiazana.is_active:
                logger.info("Zakup %s firmy %s uzgodniony przed webhookiem", sid, tenant.id)

    if powiazana is None:
        return wynik
    if not powiazana.is_active:
        return {**wynik, "status": "nieaktywna"}

    plan_firmy = get_plan(powiazana.plan_type)
    return {
        "status": "aktywna",
        "plan": powiazana.plan_type,
        "plan_name": plan_firmy.name if plan_firmy else powiazana.plan_type,
        "access_until": powiazana.end_date,
    }


@extend_schema(
    tags=["Panel — płatności"],
    summary="Cennik i bieżąca subskrypcja",
    description=(
        "Katalog planów wraz ze stanem subskrypcji firmy. Panel bierze ceny "
        "stąd, a nie z własnej kopii — inaczej cennik rozjechałby się z tym, "
        "co naprawdę obowiązuje przy zakupie."
    ),
    responses={200: BillingOverviewSerializer},
)
class BillingOverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = request.user.tenant
        subscription = getattr(tenant, "subscription", None)
        biezacy = subscription.plan_type if subscription else None
        biezacy_plan = get_plan(biezacy)
        aktywna = bool(subscription and subscription.is_active)
        zaplanowany = get_plan(subscription.zaplanowany_plan) if aktywna else None

        return Response(
            {
                "current": {
                    "plan": biezacy,
                    # Plan spoza cennika (subskrypcje sprzed katalogu) pokazujemy
                    # pod jego własną nazwą, zamiast udawać, że go nie ma
                    "name": biezacy_plan.name if biezacy_plan else biezacy,
                    "in_catalogue": biezacy_plan is not None,
                    "is_active": bool(subscription and subscription.is_active),
                    "used": subscription.current_message_count if subscription else 0,
                    "limit": subscription.message_limit if subscription else 0,
                    "renews_at": subscription.end_date if subscription else None,
                    "stripe_status": subscription.stripe_status if subscription else "",
                    "access_until": (
                        subscription.end_date if subscription and subscription.is_active else None
                    ),
                    # Z aktywną subskrypcją Stripe plan zmienia się w portalu -
                    # nowy zakup założyłby drugą subskrypcję
                    "has_stripe_subscription": aktywna_subskrypcja_stripe(tenant) is not None,
                    "portal_available": bool(tenant.stripe_customer_id),
                    "can_manage": getattr(request.user, "role", None) == "owner",
                    # Zmiany zaplanowane w Stripe - bez nich panel pokazywał
                    # anulowaną subskrypcję jak zwykły, odnawiany plan
                    "cancel_at": subscription.anulowanie_od if aktywna else None,
                    "scheduled_plan": zaplanowany.code if zaplanowany else None,
                    "scheduled_plan_name": zaplanowany.name if zaplanowany else None,
                    "scheduled_plan_from": (
                        subscription.zaplanowany_plan_od if zaplanowany else None
                    ),
                },
                "plans": [
                    {
                        "code": plan.code,
                        "name": plan.name,
                        "price_pln": plan.price_pln,
                        "price_pln_yearly": plan.price_pln_yearly,
                        "message_limit": plan.message_limit,
                        "branding": plan.branding,
                        # Zostawiamy dla zgodności z panelem, który pyta o białą
                        # etykietę wprost; poziom brandingu jest teraz trzystopniowy
                        "white_label": plan.branding == BRANDING_WLASNY,
                        "knowledge_base_mb": plan.knowledge_base_mb,
                        "max_domains": plan.max_domains,
                        "max_seats": plan.max_seats,
                        # Bez identyfikatora ceny w Stripe nie da się kupić —
                        # panel ma to pokazać zamiast prowadzić w ślepy zaułek
                        "available": bool(settings.STRIPE_PRICE_IDS.get(plan.code)),
                        # Tylko przy aktywnej subskrypcji: po anulowaniu plan był
                        # oznaczony jako obecny i nie dało się go kupić ponownie
                        "current": aktywna and plan.code == biezacy,
                    }
                    for plan in PLANS.values()
                ],
            }
        )


@extend_schema(
    tags=["Panel — płatności"],
    summary="Rozpocznij płatność za plan",
    description="Tylko właściciel firmy: zakup zakłada subskrypcję i obciąża kartę.",
    request=CheckoutRequestSerializer,
    responses={200: CheckoutResponseSerializer, 400: ErrorSerializer},
)
class CreateCheckoutSessionView(APIView):
    # Wcześniej wystarczało zalogowanie, więc plan mógł kupić także pracownik
    # albo konto tylko do podglądu.
    permission_classes = [IsOwner]

    def post(self, request):
        checkout_url = create_checkout_session(
            tenant=request.user.tenant,
            plan_code=request.data.get("plan_type"),
            email=request.user.email,
        )
        return Response({"checkout_url": checkout_url})


@extend_schema(
    tags=["Panel — płatności"],
    summary="Otwórz portal klienta Stripe",
    description=(
        "Tylko właściciel firmy. Z `plan_type` portal otwiera ekran potwierdzenia "
        "zmiany planu na bieżącej subskrypcji: wyższy plan od razu z dopłatą za "
        "resztę okresu, niższy od następnego okresu. Bez `plan_type` - karta, "
        "faktury i anulowanie."
    ),
    request=PortalRequestSerializer,
    responses={200: PortalResponseSerializer, 400: ErrorSerializer},
)
class BillingPortalView(APIView):
    permission_classes = [IsOwner]

    def post(self, request):
        portal_url = otworz_portal(
            tenant=request.user.tenant,
            plan_code=request.data.get("plan_type") or None,
        )
        return Response({"portal_url": portal_url})


@extend_schema(
    tags=["Panel — płatności"],
    summary="Stan konkretnego zakupu",
    description=(
        "Strona sukcesu po powrocie ze Stripe. `aktywna` - płatność zakończona "
        "i plan działa; `w_toku` - Stripe jeszcze przetwarza płatność; "
        "`wygasla` - sesja wygasła bez zapłaty; `nieaktywna` - subskrypcja "
        "z tego zakupu już nie działa. Sesja innej firmy daje 404."
    ),
    responses={200: CheckoutStatusSerializer, 404: ErrorSerializer, 503: ErrorSerializer},
)
class CheckoutSessionStatusView(APIView):
    permission_classes = [IsOwner]

    def get(self, request, session_id):
        return Response(stan_zakupu(request.user.tenant, session_id))


@extend_schema(
    tags=["Publiczne"],
    summary="Cennik dla strony sprzedażowej",
    responses={200: PublicPricingSerializer},
    description=(
        "Publiczny katalog planów — bez subskrypcji i bez logowania. "
        "Strona sprzedażowa bierze ceny stąd, żeby nie trzymać ich własnej "
        "kopii, która rozjedzie się przy pierwszej zmianie cennika."
    ),
)
class PublicPricingView(APIView):
    authentication_classes = ()
    permission_classes = ()

    def get(self, request):
        return Response(
            {
                "plans": [
                    {
                        "code": plan.code,
                        "name": plan.name,
                        "price_pln": plan.price_pln,
                        "price_pln_yearly": plan.price_pln_yearly,
                        "message_limit": plan.message_limit,
                        "knowledge_base_mb": plan.knowledge_base_mb,
                        "max_domains": plan.max_domains,
                        "max_seats": plan.max_seats,
                        "branding": plan.branding,
                        # Realna różnica między planami, od niedawna faktycznie
                        # działająca — a klient jej nie widział. None znaczy
                        # „odświeżanie wyłącznie na żądanie".
                        "recrawl_days": plan.recrawl_days,
                    }
                    for plan in PLANS.values()
                ],
                "pakiet": {
                    "wiadomosci": PAKIET_WIADOMOSCI,
                    "cena_pln": PAKIET_CENA_PLN,
                },
            }
        )
