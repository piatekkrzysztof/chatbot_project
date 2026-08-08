import logging

import stripe
from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.plans import PLANS, get_plan
from api.schemas import CheckoutRequestSerializer, CheckoutResponseSerializer, ErrorSerializer

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
