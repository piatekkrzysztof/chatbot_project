import stripe
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError
from django.conf import settings

# stripe.api_key = settings.STRIPE_SECRET_KEY

PRICE_IDS = {
    "pro": "price_abc123",
    "enterprise": "price_def456",
}


class CreateCheckoutSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        stripe.api_key = settings.STRIPE_SECRET_KEY
        plan_type = request.data.get("plan_type")
        price_id = PRICE_IDS.get(plan_type)

        if not price_id:
            raise ValidationError("Niepoprawny plan.")

        user = request.user
        tenant = user.tenant

        checkout_session = stripe.checkout.Session.create(
            customer_email=user.email,
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=settings.STRIPE_SUCCESS_URL + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=settings.STRIPE_CANCEL_URL,
            metadata={"tenant_id": str(tenant.id)},
        )

        return Response({"checkout_url": checkout_session.url})
