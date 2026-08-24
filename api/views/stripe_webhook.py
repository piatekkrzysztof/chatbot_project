"""
Odbiór zdarzeń ze Stripe.

Ten kod nigdy się nie wykonał: nie był podpięty pod żaden URL, więc Stripe nie
miał dokąd wysyłać zdarzeń. Nawet gdyby był, płatność niczego by nie zmieniła —
aktualizował pola na modelu Tenant, a limity wiadomości egzekwuje
SubscriptionMiddleware na podstawie modelu Subscription. Klient mógł zapłacić
i nie dostać ani jednej wiadomości więcej.

Teraz źródłem prawdy jest Subscription: to ona decyduje o dostępie, więc to ona
musi się zmieniać po opłaceniu. Pola na Tenant zostają zsynchronizowane, bo
korzysta z nich panel administracyjny.
"""
import logging
from datetime import timedelta

import stripe
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from accounts.models import Subscription, Tenant
from accounts.plans import get_plan

logger = logging.getLogger(__name__)

# Okres opłacony z góry. Stripe i tak przypomni o sobie przy odnowieniu,
# a zapas chroni przed odcięciem klienta, gdy zdarzenie odnowienia się spóźni.
OKRES_ROZLICZENIOWY = timedelta(days=31)


def activate_subscription(tenant, plan_code):
    """
    Nadaje firmie limity wykupionego planu.

    Subskrypcja może jeszcze nie istnieć (rejestracja od razu z płatnością),
    więc tworzymy ją, gdy trzeba.
    """
    plan = get_plan(plan_code)
    today = timezone.now().date()

    limit = plan.message_limit if plan else 1_000
    nazwa = plan.code if plan else (plan_code or "unknown")

    subscription, created = Subscription.objects.get_or_create(
        tenant=tenant,
        defaults={
            "plan_type": nazwa,
            "start_date": today,
            "end_date": today + OKRES_ROZLICZENIOWY,
            "message_limit": limit,
        },
    )

    if not created:
        subscription.plan_type = nazwa
        subscription.message_limit = limit
        subscription.is_active = True
        subscription.start_date = today
        subscription.end_date = today + OKRES_ROZLICZENIOWY
        subscription.save(update_fields=[
            "plan_type", "message_limit", "is_active", "start_date", "end_date",
        ])

    # Pola na Tenant są tylko odbiciem stanu — panel admina po nich filtruje
    tenant.subscription_status = "active"
    tenant.subscription_plan = nazwa
    tenant.save(update_fields=["subscription_status", "subscription_plan"])

    return subscription


def suspend_subscription(tenant, powod):
    Subscription.objects.filter(tenant=tenant).update(is_active=False)
    tenant.subscription_status = "suspended"
    tenant.save(update_fields=["subscription_status"])
    logger.warning("Subskrypcja wstrzymana (%s): tenant=%s", powod, tenant.id)


def _metadane_subskrypcji_z_faktury(faktura):
    """
    Metadane subskrypcji, do której należy faktura.

    Faktura ma WŁASNE pole `metadata`, niezależne od metadanych subskrypcji —
    a my ustawiamy je wyłącznie na sesji płatności i na subskrypcji. Czytanie
    `faktura["metadata"]` zwracało więc pusty słownik i zdarzenia odnowienia
    kończyły się na gałęzi „bez tenant_id — pomijam". Stripe dostawał 200,
    w jego panelu widniało zielone „delivered", a subskrypcja klienta nie
    przedłużała się mimo opłaconej faktury.

    Adres subskrypcji na fakturze przesuwał się między wersjami API, dlatego
    sprawdzamy kilka miejsc zamiast zakładać jedno. W nowszych wersjach
    metadane leżą wprost w `parent.subscription_details` i wtedy nie trzeba
    nawet pytać Stripe'a.
    """
    szczegoly = (
        (faktura.get("parent") or {}).get("subscription_details")
        or faktura.get("subscription_details")
        or {}
    )
    if szczegoly.get("metadata"):
        return szczegoly["metadata"]

    identyfikator = (
        faktura.get("subscription")
        or szczegoly.get("subscription")
    )
    # Bywa rozwinięty do pełnego obiektu zamiast samego identyfikatora
    if isinstance(identyfikator, dict):
        return identyfikator.get("metadata") or {}
    if not identyfikator:
        return {}

    try:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        return stripe.Subscription.retrieve(identyfikator).get("metadata") or {}
    except Exception:
        logger.exception("Nie udało się pobrać subskrypcji %s ze Stripe", identyfikator)
        return {}


def _metadane_zdarzenia(event_type, data):
    """
    Metadane niosące tenant_id — zależnie od tego, czego dotyczy zdarzenie.

    Sesja płatności i subskrypcja mają je wprost. Faktura wymaga dojścia
    do subskrypcji, bo własnych metadanych nigdy jej nie nadajemy.
    """
    wlasne = data.get("metadata") or {}
    if wlasne.get("tenant_id"):
        return wlasne
    if event_type.startswith("invoice."):
        return _metadane_subskrypcji_z_faktury(data)
    return wlasne


# csrf_exempt MUSI stać bezpośrednio nad tym widokiem. Stripe wysyła POST bez
# ciasteczka sesji i bez tokenu CSRF, więc bez tego Django odrzuca każde
# zdarzenie kodem 403 — zanim kod webhooka w ogóle się wykona. W panelu Stripe
# wygląda to jak nieudana dostawa, a w bazie nie dzieje się nic.
@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        logger.warning("Nieprawidłowa treść żądania ze Stripe")
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        # Bez poprawnego podpisu każdy mógłby aktywować sobie dowolny plan
        logger.warning("Błędna sygnatura webhooka Stripe")
        return HttpResponse(status=400)

    data = event["data"]["object"]
    metadata = _metadane_zdarzenia(event["type"], data)
    tenant_id = metadata.get("tenant_id")

    if not tenant_id:
        # Zwracamy 200: bez tenant_id nie ma czego obsłużyć, a kod błędu
        # kazałby Stripe'owi ponawiać to zdarzenie w nieskończoność
        logger.warning("Zdarzenie %s bez tenant_id — pomijam", event["type"])
        return HttpResponse(status=200)

    tenant = Tenant.objects.filter(id=tenant_id).first()
    if tenant is None:
        logger.warning("Zdarzenie %s dla nieistniejącej firmy %s", event["type"], tenant_id)
        return HttpResponse(status=200)

    event_type = event["type"]

    if event_type in ("checkout.session.completed", "invoice.payment_succeeded"):
        subscription = activate_subscription(tenant, metadata.get("plan"))
        logger.info(
            "Subskrypcja aktywna: tenant=%s plan=%s limit=%s",
            tenant.id, subscription.plan_type, subscription.message_limit,
        )

    elif event_type == "invoice.payment_failed":
        suspend_subscription(tenant, "nieudana płatność")

    elif event_type == "customer.subscription.deleted":
        suspend_subscription(tenant, "subskrypcja anulowana")

    else:
        logger.info("Nieobsługiwane zdarzenie Stripe: %s", event_type)

    return HttpResponse(status=200)
