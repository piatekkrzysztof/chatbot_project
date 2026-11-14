"""Uzgadnianie po utracie webhooka, w ograniczonych porcjach na obecnym workerze."""

import logging
from datetime import timedelta
from time import monotonic

import stripe
from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import OperationalError, transaction
from django.db.models import F, Q
from django.utils import timezone

from accounts.stripe_sync import KontrolaStripe

logger = logging.getLogger(__name__)
LIMIT_FIRM = 25
BUDZET_SEKUND = 50


#: Błędy, po których sensowne jest samo ponowienie: sieć i limit zapytań.
BLEDY_CHWILOWE = (stripe.APIConnectionError, stripe.RateLimitError)
_BLAD_CHWILOWY_WAZNY_S = 6 * 3600


def _klucz_bledu_chwilowego(tenant):
    return f"stripe-kontrola-chwilowy:{tenant.pk}"


def _pierwszy_blad_chwilowy(tenant):
    """
    True przy pierwszym chwilowym błędzie firmy od ostatniego udanego uzgodnienia.

    Do 2.32.33 pojedynczy błąd sieci przy rozmowie z API Stripe od razu
    oznaczał firmę jako wymagającą reakcji i wysyłał alarm do operatora.
    Bez pamięci podręcznej zachowujemy się jak dotąd: alarm.
    """
    try:
        return bool(cache.add(_klucz_bledu_chwilowego(tenant), 1, timeout=_BLAD_CHWILOWY_WAZNY_S))
    except Exception:
        return False


def _zapomnij_bledy_chwilowe(tenant):
    try:
        cache.delete(_klucz_bledu_chwilowego(tenant))
    except Exception:
        logger.warning("Nie udalo sie wyczyscic licznika bledow Stripe: tenant=%s", tenant.pk)


def brakujace_ustawienia_stripe():
    """
    Zmienne Stripe, których brakuje w środowisku TEGO procesu.

    Uzgadnianie działa na workerze, a zmienne w Renderze ustawia się osobno
    dla każdej usługi. Do 2.32.19 blueprint dawał `STRIPE_*` tylko usłudze
    web (przegląd 2026-11, R02). Bez klucza każda firma kończyła się błędem
    i alarmem „sprawdź Stripe i logi", który nie mówił, czego szukać; bez
    cen plan wracał do planu z dnia zakupu.
    """
    braki = [] if settings.STRIPE_SECRET_KEY else ["STRIPE_SECRET_KEY"]
    braki += [
        f"STRIPE_PRICE_{kod.upper()}" for kod, cena in settings.STRIPE_PRICE_IDS.items() if not cena
    ]
    return braki


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
    except (ZdarzenieDoPonowienia, stripe.error.StripeError) as blad:
        # Synchronizacja opakowuje błąd Stripe w ZdarzenieDoPonowienia,
        # więc o tym, czy był chwilowy, mówi dopiero przyczyna.
        chwilowy = isinstance(blad, BLEDY_CHWILOWE) or isinstance(blad.__cause__, BLEDY_CHWILOWE)
        if chwilowy and _pierwszy_blad_chwilowy(tenant):
            # Jedno zerwane połączenie albo limit zapytań to nie jest sprawa
            # dla operatora. Cofamy znacznik próby, żeby następny przebieg
            # spróbował od razu, a alarm zostawiamy na powtórkę.
            aktualna_proba.update(probowano_at=poprzednia_proba)
            logger.warning(
                "Kontrola Stripe: chwilowy blad (%s), ponowie: tenant=%s",
                type(blad.__cause__ or blad).__name__,
                tenant.pk,
            )
        else:
            aktualna_proba.update(blad="wymaga_uzgodnienia")
            logger.error("Kontrola Stripe wymaga reakcji: tenant=%s", tenant.pk)
    else:
        _zapomnij_bledy_chwilowe(tenant)
        aktualna_proba.update(blad="", alarm_at=None, uzgodniono_at=timezone.now())


def _alarmuj():
    from accounts.czuwanie import adresy_operatora

    prog = timezone.now() - timedelta(hours=1)
    oczekujace = list(
        KontrolaStripe.objects.exclude(blad="")
        .filter(Q(alarm_at__isnull=True) | Q(alarm_at__lt=prog))
        .order_by("probowano_at", "pk")[:50]
    )
    if not oczekujace:
        return
    braki = brakujace_ustawienia_stripe()
    przyczyna = (
        f"Na workerze brakuje zmiennych: {', '.join(braki)}. Ustaw je jak na web.\n\n"
        if braki
        else ""
    )
    tresc = (
        "Kontrola płatności wymaga reakcji operatora. Sprawdź Stripe i logi.\n\n"
        + przyczyna
        + "\n".join(
            f"Firma {k.tenant_id}: {k.blad}; ostatnia próba {k.probowano_at}." for k in oczekujace
        )
    )
    try:
        if not send_mail(
            "Stripe: nieuzgodnione płatności",
            tresc,
            settings.DEFAULT_FROM_EMAIL,
            adresy_operatora(),
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
    braki = brakujace_ustawienia_stripe()
    if firmy and braki:
        logger.error(
            "Uzgadnianie płatności bez zmiennych %s - ustaw je na workerze jak na web",
            ", ".join(braki),
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
