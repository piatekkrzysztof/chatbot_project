"""Uzgadnianie po utracie webhooka, w ograniczonych porcjach na obecnym workerze."""

import logging
from datetime import timedelta
from time import monotonic

import stripe
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import OperationalError, transaction
from django.db.models import F, Q
from django.utils import timezone

from accounts.stripe_sync import KontrolaStripe

logger = logging.getLogger(__name__)
LIMIT_FIRM = 25
BUDZET_SEKUND = 50


def kandydaci():
    from accounts.models import Tenant

    return Tenant.objects.filter(
        Q(subscription__stripe_subscription_id__gt="") | Q(proba_zakupu__sesja_id__gt="")
    )


def _uzgodnij_firme(tenant):
    from accounts.checkout import ProbaZakupu
    from accounts.models import Subscription
    from api.views.stripe_webhook import (
        ZdarzenieDoPonowienia,
        _identyfikator,
        synchronizuj_subskrypcje,
    )

    sid = (
        Subscription.objects.filter(tenant=tenant)
        .values_list("stripe_subscription_id", flat=True)
        .first()
    )
    if sid:
        synchronizuj_subskrypcje(tenant, sid)
    identyfikatory = []
    proba = ProbaZakupu.objects.filter(tenant=tenant).exclude(sesja_id="").first()
    if proba:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        sesja = stripe.checkout.Session.retrieve(proba.sesja_id)
        if str((sesja.get("metadata") or {}).get("tenant_id")) != str(tenant.pk):
            raise ZdarzenieDoPonowienia("Niezgodne powiązanie Checkout")
        if sesja.get("status") == "complete":
            nowy_sid = _identyfikator(sesja.get("subscription"))
            if not nowy_sid:
                raise ZdarzenieDoPonowienia("Checkout bez subskrypcji")
            if nowy_sid != sid:
                identyfikatory.append(nowy_sid)
        elif sesja.get("status") not in ("open", "expired"):
            raise ZdarzenieDoPonowienia("Nieznany stan Checkout")
    for identyfikator in identyfikatory:
        synchronizuj_subskrypcje(tenant, identyfikator)


def _kontroluj(tenant):
    from api.views.stripe_webhook import SynchronizacjaZajeta, ZdarzenieDoPonowienia

    KontrolaStripe.objects.get_or_create(tenant=tenant)
    try:
        with transaction.atomic():
            kontrola = KontrolaStripe.objects.select_for_update(nowait=True).get(tenant=tenant)
            if kontrola.probowano_at and kontrola.probowano_at > timezone.now() - timedelta(
                hours=1
            ):
                return  # Duplikat zadania wybrał tę samą firmę przed zapisem próby.
            poprzednia_proba = kontrola.probowano_at
            kontrola.probowano_at = timezone.now()
            kontrola.save(update_fields=["probowano_at"])
    except OperationalError as blad:
        if getattr(blad.__cause__, "pgcode", None) == "55P03":
            return  # Druga kopia zadania kontroluje tę samą firmę.
        raise
    # Znacznik jest zatwierdzony. Każda subskrypcja ma własną transakcję,
    # więc blokady Tenant z poprzedniego zapisu nie obejmują kolejnego HTTP.
    aktualna_proba = KontrolaStripe.objects.filter(
        pk=kontrola.pk, probowano_at=kontrola.probowano_at
    )
    try:
        _uzgodnij_firme(tenant)
    except SynchronizacjaZajeta:
        aktualna_proba.update(probowano_at=poprzednia_proba)
    except (ZdarzenieDoPonowienia, stripe.error.StripeError):
        aktualna_proba.update(blad="wymaga_uzgodnienia")
        logger.error("Kontrola Stripe wymaga reakcji: tenant=%s", tenant.pk)
    else:
        aktualna_proba.update(blad="", alarm_at=None, uzgodniono_at=timezone.now())


def _alarmuj():
    from accounts.czuwanie import adres_operatora

    prog = timezone.now() - timedelta(hours=1)
    oczekujace = list(
        KontrolaStripe.objects.exclude(blad="")
        .filter(Q(alarm_at__isnull=True) | Q(alarm_at__lt=prog))
        .order_by("probowano_at", "pk")[:50]
    )
    if not oczekujace:
        return
    tresc = "Kontrola płatności wymaga reakcji operatora. Sprawdź Stripe i logi.\n\n" + "\n".join(
        f"Firma {k.tenant_id}: {k.blad}; ostatnia próba {k.probowano_at}." for k in oczekujace
    )
    try:
        if not send_mail(
            "Stripe: nieuzgodnione płatności",
            tresc,
            settings.DEFAULT_FROM_EMAIL,
            [adres_operatora()],
            fail_silently=False,
        ):
            raise RuntimeError("Nie wysłano alarmu Stripe")
    except Exception:
        logger.exception("Nie udało się wysłać alarmu kontroli Stripe")
        return
    # Jeśli w międzyczasie wykonano nową kontrolę, nie wyciszamy nowego wyniku.
    for k in oczekujace:
        KontrolaStripe.objects.filter(pk=k.pk, probowano_at=k.probowano_at, blad=k.blad).update(
            alarm_at=timezone.now()
        )


@shared_task(ignore_result=True, soft_time_limit=110, time_limit=120)
def uzgodnij_platnosci():
    poczatek = monotonic()
    prog = timezone.now() - timedelta(hours=1)
    firmy = list(
        kandydaci()
        .filter(
            Q(kontrola_stripe__probowano_at__isnull=True)
            | Q(kontrola_stripe__probowano_at__lt=prog)
        )
        .order_by(F("kontrola_stripe__probowano_at").asc(nulls_first=True), "pk")[:LIMIT_FIRM]
    )
    sprawdzone = 0
    for tenant in firmy:
        if monotonic() - poczatek >= BUDZET_SEKUND:
            break
        _kontroluj(tenant)
        sprawdzone += 1
    _alarmuj()
    logger.info("Kontrola Stripe: sprawdzono=%s wybrano=%s", sprawdzone, len(firmy))
    return sprawdzone
