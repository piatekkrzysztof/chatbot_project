"""Checkout odporny na równoległe karty i utratę odpowiedzi Stripe.

Parametry i klucz zatwierdzamy PRZED pierwszym zewnętrznym utworzeniem sesji.
Nieznany wynik nigdy nie uprawnia do utworzenia nowej próby. Blokujemy tylko
slot zakupu, nie firmę używaną przez czat, limity i webhooki.
"""

import uuid
from datetime import timedelta

from django.db import OperationalError, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from accounts.checkout import ProbaZakupu
from accounts.models import Subscription, Tenant

GODZINY_PONAWIANIA = 23  # Stripe gwarantuje przechowanie klucza przez co najmniej 24 h.
STATUSY_KONCOWE = frozenset({"canceled", "incomplete_expired"})


class CheckoutZajety(APIException):
    status_code = 409
    default_detail = "Płatność jest właśnie przygotowywana. Spróbuj ponownie za chwilę."


class CheckoutDoWyjasnienia(APIException):
    status_code = 503
    default_detail = (
        "Nie możemy jeszcze potwierdzić stanu poprzedniej płatności. "
        "Spróbuj ponownie później, a jeśli problem pozostanie, skontaktuj się z nami."
    )


class CheckoutZakonczony(APIException):
    status_code = 409
    default_detail = (
        "Poprzednia płatność została już zakończona lub jest rozliczana. "
        "Sprawdź zakładkę Subskrypcja zamiast rozpoczynać drugi zakup."
    )


def _slot(tenant):
    return ProbaZakupu.objects.select_for_update(nowait=True).get(tenant=tenant)


def _bez_aktywnej_subskrypcji(tenant):
    if (
        Subscription.objects.filter(
            tenant=tenant, is_active=True, stripe_status__in=("active", "trialing", "past_due")
        )
        .exclude(stripe_subscription_id="")
        .exists()
    ):
        raise CheckoutZakonczony()


def _zakonczona_subskrypcja(stripe, sesja):
    identyfikator = sesja.get("subscription")
    if isinstance(identyfikator, dict):
        identyfikator = identyfikator.get("id")
    if not isinstance(identyfikator, str) or not identyfikator:
        raise CheckoutDoWyjasnienia()
    subskrypcja = stripe.Subscription.retrieve(identyfikator)
    if subskrypcja.get("status") not in STATUSY_KONCOWE:
        raise CheckoutZakonczony()


def _sprawdz_stare_sesje(stripe, proba):
    """Jednorazowo dla firm sprzed migracji; obejmuje także fallback customer_email."""
    parametry = {
        "limit": 100,
        "created": {
            "gte": int((proba.rozpoczeta_at - timedelta(days=1)).timestamp()),
            "lte": int(proba.rozpoczeta_at.timestamp()),
        },
    }
    # Starsza sesja nie może być otwarta dłużej niż 24 h. Nie filtrujemy po
    # customer: poprzedni kod mógł użyć fallbacku bez zapisania tej kartoteki.
    for _ in range(5):
        strona = stripe.checkout.Session.list(**parametry)
        for sesja in strona["data"]:
            if sesja.get("mode") != "subscription" or str(
                (sesja.get("metadata") or {}).get("tenant_id")
            ) != str(proba.tenant_id):
                continue
            if sesja.get("status") == "open":
                wynik = stripe.checkout.Session.expire(sesja["id"])
                if wynik.get("status") != "expired":
                    raise CheckoutDoWyjasnienia()
            elif sesja.get("status") == "complete":
                _zakonczona_subskrypcja(stripe, sesja)
            elif sesja.get("status") != "expired":
                raise CheckoutDoWyjasnienia()
        if not strona.get("has_more"):
            proba.sprawdzone_stare_sesje = True
            return
        if not strona["data"]:
            break
        parametry["starting_after"] = strona["data"][-1]["id"]
    # Niepełna lista nie jest dowodem braku otwartych płatności.
    raise CheckoutDoWyjasnienia()


def _przygotuj(stripe, tenant, plan, price_id, email, frontend, kartoteka):
    with transaction.atomic(durable=True):
        proba = _slot(tenant)
        _bez_aktywnej_subskrypcji(tenant)
        if not proba.sprawdzone_stare_sesje:
            _sprawdz_stare_sesje(stripe, proba)
        if not proba.parametry:
            # Świeży Tenant: request mógł mieć starą kopię sprzed innego zakupu.
            aktualny_tenant = Tenant.objects.get(pk=tenant.pk)
            klient = kartoteka(aktualny_tenant, email)
            rozpoznanie = (
                {"customer": klient}
                if klient
                else {"customer_email": email or aktualny_tenant.owner_email}
            )
            proba.rozpoczeta_at = timezone.now()
            metadane = {
                "tenant_id": str(tenant.pk),
                "plan": plan.code,
                "checkout_attempt": str(proba.klucz),
            }
            proba.parametry = {
                "mode": "subscription",
                **rozpoznanie,
                "line_items": [{"price": price_id, "quantity": 1}],
                "success_url": f"{frontend}/platnosc/sukces?session_id={{CHECKOUT_SESSION_ID}}",
                "cancel_url": f"{frontend}/platnosc/anulowano",
                "metadata": metadane,
                "subscription_data": {"metadata": metadane},
                "expires_at": int(proba.rozpoczeta_at.timestamp()) + 86400,
            }
        proba.save()


def _zamknij(proba):
    proba.klucz = uuid.uuid4()
    proba.parametry = {}
    proba.sesja_id = ""
    proba.save(update_fields=["klucz", "parametry", "sesja_id"])


def _uzgodnij(stripe, tenant, plan, price_id):
    with transaction.atomic():
        proba = _slot(tenant)
        _bez_aktywnej_subskrypcji(tenant)
        if not proba.parametry:
            return None  # Równoległe żądanie zamknęło poprzednią sesję.
        if proba.sesja_id:
            sesja = stripe.checkout.Session.retrieve(proba.sesja_id)
        else:
            if timezone.now() - proba.rozpoczeta_at >= timedelta(hours=GODZINY_PONAWIANIA):
                # Po wygaśnięciu pamięci idempotencji ten sam klucz mógłby
                # utworzyć drugi abonament. Wymagane uzgodnienie przez operatora.
                raise CheckoutDoWyjasnienia()
            sesja = stripe.checkout.Session.create(
                **proba.parametry, idempotency_key=f"checkout-{tenant.pk}-{proba.klucz}"
            )
            if not isinstance(sesja.get("id"), str) or not sesja["id"]:
                raise CheckoutDoWyjasnienia()
            proba.sesja_id = sesja["id"]
            proba.save(update_fields=["sesja_id"])
            # Idempotentny replay może zwrócić DAWNĄ odpowiedź create, mimo
            # że sesja jest już opłacona lub wygasła. Zatwierdź identyfikator
            # i sprawdź aktualny stan przez retrieve w kolejnym przebiegu.
            return None

        status = sesja.get("status")
        if status == "complete":
            _zakonczona_subskrypcja(stripe, sesja)
            _zamknij(proba)
            return None
        if status == "expired":
            _zamknij(proba)
            return None
        if status != "open":
            raise CheckoutDoWyjasnienia()
        ten_sam_plan = (
            proba.parametry["metadata"]["plan"] == plan.code
            and proba.parametry["line_items"][0]["price"] == price_id
        )
        if not ten_sam_plan:
            wynik = stripe.checkout.Session.expire(proba.sesja_id)
            if wynik.get("status") != "expired":
                raise CheckoutDoWyjasnienia()
            _zamknij(proba)
            return None
        if not isinstance(sesja.get("url"), str) or not sesja["url"]:
            raise CheckoutDoWyjasnienia()
        return sesja


def pojedyncza_sesja(stripe, tenant, plan, price_id, email, frontend, kartoteka):
    # Zatwierdzony slot i parametry muszą przetrwać rollback żądania po
    # utracie odpowiedzi Stripe. durable=True zabrania ukrytej transakcji nadrzędnej.
    with transaction.atomic(durable=True):
        ProbaZakupu.objects.get_or_create(tenant=tenant)
    try:
        for _ in range(5):
            _przygotuj(stripe, tenant, plan, price_id, email, frontend, kartoteka)
            sesja = _uzgodnij(stripe, tenant, plan, price_id)
            if sesja is not None:
                return sesja
    except OperationalError as blad:
        if getattr(blad.__cause__, "pgcode", None) == "55P03":
            raise CheckoutZajety() from blad
        raise
    raise CheckoutZajety()
