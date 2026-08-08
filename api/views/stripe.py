import logging

import stripe
from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.plans import PLANS, get_plan
from api.schemas import (
    BillingOverviewSerializer, CheckoutRequestSerializer,
    CheckoutResponseSerializer, ErrorSerializer,
)

logger = logging.getLogger(__name__)


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
        raise ValidationError(
            f"Nieznany plan: {plan_code}. Dostępne: {', '.join(PLANS)}."
        )

    price_id = settings.STRIPE_PRICE_IDS.get(plan.code)
    if not price_id:
        logger.error("Brak identyfikatora ceny Stripe dla planu %s", plan.code)
        raise ValidationError(
            f"Plan {plan.name} nie jest jeszcze dostępny do zakupu. "
            "Skontaktuj się z nami."
        )

    stripe.api_key = settings.STRIPE_SECRET_KEY
    frontend = settings.FRONTEND_URL.rstrip("/")

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer_email=email or tenant.owner_email,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{frontend}/platnosc/sukces?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{frontend}/platnosc/anulowano",
        metadata={"tenant_id": str(tenant.id), "plan": plan.code},
        # Metadane sesji nie przechodzą na subskrypcję, a zdarzenia odnowienia
        # dotyczą właśnie subskrypcji — bez tego nie da się ich powiązać z firmą
        subscription_data={
            "metadata": {"tenant_id": str(tenant.id), "plan": plan.code}
        },
    )
    return session.url


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

        return Response({
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
            },
            "plans": [
                {
                    "code": plan.code,
                    "name": plan.name,
                    "price_pln": plan.price_pln,
                    "message_limit": plan.message_limit,
                    "white_label": plan.white_label,
                    # Bez identyfikatora ceny w Stripe nie da się kupić —
                    # panel ma to pokazać zamiast prowadzić w ślepy zaułek
                    "available": bool(settings.STRIPE_PRICE_IDS.get(plan.code)),
                    "current": plan.code == biezacy,
                }
                for plan in PLANS.values()
            ],
        })


@extend_schema(
    tags=["Panel — płatności"],
    summary="Rozpocznij płatność za plan",
    request=CheckoutRequestSerializer,
    responses={200: CheckoutResponseSerializer, 400: ErrorSerializer},
)
class CreateCheckoutSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        checkout_url = create_checkout_session(
            tenant=request.user.tenant,
            plan_code=request.data.get("plan_type"),
            email=request.user.email,
        )
        return Response({"checkout_url": checkout_url})
