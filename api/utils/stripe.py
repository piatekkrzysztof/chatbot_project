import stripe
from django.conf import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

def create_checkout_session(tenant):
    return stripe.checkout.Session.create(
        success_url=f"{settings.FRONTEND_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.FRONTEND_URL}/cancelled",
        customer_email=tenant.owner_email,
        mode="subscription",
        line_items=[{
            "price": settings.STRIPE_DEFAULT_PRICE_ID,
            "quantity": 1,
        }],
        metadata={
            "tenant_id": str(tenant.id),
        }
    ).url