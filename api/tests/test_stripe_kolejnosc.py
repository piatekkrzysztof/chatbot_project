"""A02: opóźniony odczyt nie może przywrócić starszego stanu."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connections, transaction
from rest_framework.test import APIClient

from accounts.checkout import ProbaZakupu
from accounts.models import Subscription, Tenant
from accounts.stripe_sync import KontrolaStripe
from accounts.tasks_stripe import _kontroluj
from api.tests.test_platnosci_spojnosc import DZIS, subskrypcja_stripe
from api.views.stripe import PlatnosciNiedostepne, stan_zakupu
from api.views.stripe_webhook import ZdarzenieDoPonowienia, synchronizuj_subskrypcje


def webhook():
    return (
        APIClient()
        .post(
            "/api/billing/webhook/",
            data="{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="test",
        )
        .status_code
    )


def osobne_polaczenie(funkcja):
    close_old_connections()
    try:
        return funkcja()
    finally:
        connections.close_all()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "status,plan",
    [("canceled", "pro"), ("active", "start"), ("past_due", "pro"), ("active", "pro")],
)
def test_opozniony_odczyt_nie_cofa_nowszego_stanu(settings, status, plan):
    settings.STRIPE_PRICE_IDS = {"start": "price_start", "pro": "price_pro"}
    tenant = Tenant.objects.create(name="Kolejność", owner_email="a@example.test")
    stary = subskrypcja_stripe(tenant)
    nowy = subskrypcja_stripe(tenant, status=status, plan=plan, koniec=DZIS + timedelta(days=60))
    # Istnieje powiązanie, więc anulowanie musi odebrać dostęp.
    Subscription.objects.create(
        tenant=tenant,
        plan_type="pro",
        stripe_subscription_id="sub_1",
        stripe_status="active",
        is_active=True,
        start_date="2026-01-01",
        end_date="2027-01-01",
    )
    pobrano_stary, zwolnij = Event(), Event()

    def retrieve(*args, **kwargs):
        if not pobrano_stary.is_set():
            pobrano_stary.set()
            assert zwolnij.wait(10)
            return stary
        return nowy

    event = {"type": "customer.subscription.updated", "data": {"object": {"id": "sub_1"}}}
    with (
        patch("stripe.Webhook.construct_event", return_value=event),
        patch("stripe.Subscription.retrieve", side_effect=retrieve),
        patch("api.views.stripe_webhook._powiadom_o_nieudanej_platnosci") as powiadom,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        wolny = pool.submit(osobne_polaczenie, webhook)
        try:
            assert pobrano_stary.wait(5)
            assert webhook() == 200
        finally:
            zwolnij.set()
        assert wolny.result(10) == 200
    lokalna = Subscription.objects.get(tenant=tenant)
    assert lokalna.stripe_status == status
    assert lokalna.is_active is (status != "canceled")
    assert lokalna.plan_type == plan
    if status == "active":
        assert lokalna.end_date == DZIS + timedelta(days=63)
    if status == "past_due":
        powiadom.assert_called_once()


@pytest.mark.django_db(transaction=True)
def test_webhook_i_powrot_z_checkout_maja_wspolna_blokade():
    tenant = Tenant.objects.create(name="Powrót", owner_email="a@example.test")
    inna = Tenant.objects.create(name="Inna", owner_email="b@example.test")
    ProbaZakupu.objects.create(tenant=tenant, sesja_id="cs_test_12345678")
    aktywna = subskrypcja_stripe(tenant)
    anulowana = subskrypcja_stripe(tenant, status="canceled")
    pobrano, zwolnij = Event(), Event()

    def retrieve(*args, **kwargs):
        if args[0] == "sub_inna":
            return subskrypcja_stripe(inna, sid="sub_inna")
        if not pobrano.is_set():
            pobrano.set()
            assert zwolnij.wait(10)
            return aktywna
        return anulowana

    sesja = {
        "status": "complete",
        "payment_status": "paid",
        "subscription": "sub_1",
        "metadata": {"tenant_id": str(tenant.pk), "plan": "pro"},
    }
    event = {"type": "customer.subscription.updated", "data": {"object": {"id": "sub_1"}}}
    with (
        patch("stripe.Subscription.retrieve", side_effect=retrieve),
        patch("stripe.checkout.Session.retrieve", return_value=sesja),
        patch("stripe.Webhook.construct_event", return_value=event),
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        pierwszy = pool.submit(osobne_polaczenie, lambda: synchronizuj_subskrypcje(tenant, "sub_1"))
        try:
            assert pobrano.wait(5)
            # Czat może nadal blokować Tenant podczas oczekiwania na Stripe.
            with transaction.atomic():
                Tenant.objects.select_for_update(nowait=True).get(pk=tenant.pk)
            assert synchronizuj_subskrypcje(inna, "sub_inna").is_active
            assert webhook() == 500
            with pytest.raises(PlatnosciNiedostepne):
                stan_zakupu(tenant, "cs_test_12345678")
            _kontroluj(tenant)
            assert KontrolaStripe.objects.get(tenant=tenant).probowano_at is None
        finally:
            zwolnij.set()
        pierwszy.result(10)
        assert webhook() == 200
    assert Subscription.objects.get(tenant=tenant).is_active is False


@pytest.mark.django_db(transaction=True)
def test_rollback_zwalnia_blokade_i_nie_zostawia_polowy_stanu():
    tenant = Tenant.objects.create(name="Rollback", owner_email="a@example.test")
    sub = subskrypcja_stripe(tenant)
    with patch("stripe.Subscription.retrieve", return_value=sub):
        with patch.object(Tenant, "save", side_effect=RuntimeError("awaria zapisu")):
            with pytest.raises(RuntimeError):
                synchronizuj_subskrypcje(tenant, "sub_1")
        assert not Subscription.objects.filter(tenant=tenant).exists()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(
                osobne_polaczenie, lambda: synchronizuj_subskrypcje(tenant, "sub_1")
            ).result(10)
    assert Subscription.objects.get(tenant=tenant).is_active


@pytest.mark.django_db
@pytest.mark.parametrize("zmiana", ["firma", "id"])
def test_nowy_odczyt_musi_nadal_nalezec_do_firmy(tenant, zmiana):
    sub = subskrypcja_stripe(tenant)
    if zmiana == "firma":
        sub["metadata"]["tenant_id"] = str(tenant.pk + 1)
    else:
        sub["id"] = "sub_inna"
    with patch("stripe.Subscription.retrieve", return_value=sub):
        with pytest.raises(ZdarzenieDoPonowienia):
            synchronizuj_subskrypcje(tenant, "sub_1")
    assert not Subscription.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_odrzuca_gotowa_migawke(tenant):
    with pytest.raises(ValueError):
        synchronizuj_subskrypcje(tenant, subskrypcja_stripe(tenant))
