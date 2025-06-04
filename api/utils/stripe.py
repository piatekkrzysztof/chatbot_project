import stripe
import os
from django.conf import settings

def create_checkout_session(tenant):
    stripe.api_key = getattr(settings, "STRIPE_SECRET_KEY", os.getenv("STRIPE_SECRET_KEY"))

    session = stripe.checkout.Session.create(
        success_url=f"{getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')}/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')}/cancelled",
        customer_email=tenant.owner_email,
        mode="subscription",
        line_items=[{
            "price": getattr(settings, "STRIPE_DEFAULT_PRICE_ID", os.getenv("STRIPE_DEFAULT_PRICE_ID")),
            "quantity": 1,
        }],
        metadata={
            "tenant_id": str(tenant.id),
        }
    )
    return session.url
