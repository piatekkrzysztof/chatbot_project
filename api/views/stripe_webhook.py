import stripe
import logging
import json

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from accounts.models import Tenant

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY

@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    endpoint_secret = settings.STRIPE_WEBHOOK_SECRET

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError as e:
        logger.warning(f"❌ Nieprawidłowy payload Stripe: {e}")
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError as e:
        logger.warning(f"❌ Błąd weryfikacji sygnatury Stripe: {e}")
        return HttpResponse(status=400)

    data = event["data"]["object"]
    metadata = data.get("metadata", {})

    tenant_id = metadata.get("tenant_id")
    if not tenant_id:
        logger.warning("❌ Brak tenant_id w metadanych Stripe.")
        return JsonResponse({"error": "Missing tenant_id in metadata"}, status=400)

    try:
        tenant = Tenant.objects.get(id=tenant_id)
    except Tenant.DoesNotExist:
        logger.warning(f"❌ Tenant o ID {tenant_id} nie istnieje.")
        return JsonResponse({"error": "Tenant not found"}, status=404)

    event_type = event["type"]

    if event_type == "checkout.session.completed":
        if tenant.subscription_status != "active":
            tenant.subscription_status = "active"
            tenant.subscription_plan = "paid"  # Możesz dynamicznie pobierać plan jeśli chcesz
            tenant.save()
            logger.info(f"✅ Subskrypcja AKTYWOWANA: tenant={tenant_id}")

    elif event_type == "invoice.payment_failed":
        tenant.subscription_status = "suspended"
        tenant.save()
        logger.warning(f"⚠️ Subskrypcja ZAWIESZONA: tenant={tenant_id}")

    elif event_type == "customer.subscription.deleted":
        tenant.subscription_status = "suspended"
        tenant.save()
        logger.warning(f"⚠️ Subskrypcja USUNIĘTA: tenant={tenant_id}")

    else:
        logger.info(f"ℹ️ Niewspierany event Stripe: {event_type}")

    return HttpResponse(status=200)
