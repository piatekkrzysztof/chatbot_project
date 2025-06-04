import stripe
import json
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from accounts.models import Tenant

stripe.api_key = settings.STRIPE_SECRET_KEY


@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    endpoint_secret = settings.STRIPE_WEBHOOK_SECRET

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError as e:
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError as e:
        return HttpResponse(status=400)

    data = event['data']['object']
    metadata = data.get('metadata', {})

    tenant_id = metadata.get("tenant_id")
    if not tenant_id:
        return JsonResponse({"error": "Missing tenant_id in metadata"}, status=400)

    try:
        tenant = Tenant.objects.get(id=tenant_id)
    except Tenant.DoesNotExist:
        return JsonResponse({"error": "Tenant not found"}, status=404)

    # Obsługa zdarzeń
    if event['type'] == 'checkout.session.completed':
        tenant.subscription_status = 'active'
        tenant.subscription_plan = 'paid'
        tenant.save()

    elif event['type'] == 'invoice.payment_failed':
        tenant.subscription_status = 'suspended'
        tenant.save()

    elif event['type'] == 'customer.subscription.deleted':
        tenant.subscription_status = 'suspended'
        tenant.save()

    return HttpResponse(status=200)
