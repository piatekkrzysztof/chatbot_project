from datetime import timedelta
from unittest.mock import patch

import pytest
import stripe
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from accounts.checkout import ProbaZakupu
from accounts.models import Subscription, Tenant
from accounts.stripe_sync import KontrolaStripe
from accounts.tasks_stripe import _alarmuj, uzgodnij_platnosci
from api.tests.test_platnosci_spojnosc import subskrypcja_stripe
from api.views.stripe_webhook import SynchronizacjaZajeta

pytestmark = pytest.mark.django_db


def firma():
    tenant = Tenant.objects.create(name="Kontrola", owner_email="a@example.test")
    Subscription.objects.create(
        tenant=tenant,
        plan_type="pro",
        stripe_subscription_id=f"sub_{tenant.pk}",
        stripe_status="active",
        is_active=True,
        start_date="2026-01-01",
        end_date="2027-01-01",
    )
    return tenant


def test_brak_webhooka_naprawiany_przez_zadanie():
    tenant = firma()
    with patch(
        "stripe.Subscription.retrieve",
        return_value=subskrypcja_stripe(tenant, sid=f"sub_{tenant.pk}", status="canceled"),
    ):
        assert uzgodnij_platnosci() == 1
    assert not Subscription.objects.get(tenant=tenant).is_active
    kontrola = KontrolaStripe.objects.get(tenant=tenant)
    assert kontrola.uzgodniono_at and not kontrola.blad


def test_zakup_bez_zadnego_webhooka_odnajdywany_po_checkout():
    tenant = Tenant.objects.create(name="Zakup", owner_email="a@example.test")
    ProbaZakupu.objects.create(tenant=tenant, sesja_id="cs_test_test")
    with (
        patch(
            "stripe.checkout.Session.retrieve",
            return_value={
                "status": "complete",
                "subscription": "sub_1",
                "metadata": {"tenant_id": str(tenant.pk)},
            },
        ),
        patch("stripe.Subscription.retrieve", return_value=subskrypcja_stripe(tenant)),
    ):
        assert uzgodnij_platnosci() == 1
    assert Subscription.objects.get(tenant=tenant).is_active


def test_awaria_jednej_firmy_nie_glodzi_innych_i_wysyla_alarm(settings, mailoutbox):
    settings.EMAIL_ALERTOW = "operator@example.test"
    settings.DEFAULT_FROM_EMAIL = "app@example.test"
    pierwsza, druga = firma(), firma()
    with patch(
        "stripe.Subscription.retrieve",
        side_effect=[
            stripe.error.APIConnectionError("awaria"),
            subskrypcja_stripe(druga, sid=f"sub_{druga.pk}", status="canceled"),
        ],
    ):
        assert uzgodnij_platnosci() == 2
    assert Subscription.objects.get(tenant=pierwsza).is_active
    assert not Subscription.objects.get(tenant=druga).is_active
    k = KontrolaStripe.objects.get(tenant=pierwsza)
    assert k.blad and k.alarm_at and not k.uzgodniono_at
    assert len(mailoutbox) == 1
    _alarmuj()
    assert len(mailoutbox) == 1
    KontrolaStripe.objects.filter(tenant=pierwsza).update(
        probowano_at=timezone.now() - timedelta(hours=2)
    )
    with patch(
        "stripe.Subscription.retrieve",
        return_value=subskrypcja_stripe(pierwsza, sid=f"sub_{pierwsza.pk}"),
    ):
        assert uzgodnij_platnosci() == 1
    k.refresh_from_db()
    assert k.uzgodniono_at and not k.blad and not k.alarm_at


@pytest.mark.parametrize("wynik", [0, RuntimeError("SMTP niedostępne")])
def test_niewyslany_alarm_nie_jest_uznany_za_dostarczony(wynik):
    tenant = firma()
    k = KontrolaStripe.objects.create(tenant=tenant, probowano_at=timezone.now(), blad="awaria")
    with (
        patch("accounts.czuwanie.adres_operatora", return_value="operator@example.test"),
        patch(
            "accounts.tasks_stripe.send_mail",
            side_effect=wynik if isinstance(wynik, Exception) else None,
            return_value=wynik,
        ),
    ):
        _alarmuj()
    k.refresh_from_db()
    assert k.alarm_at is None


def test_limit_pracy_i_sprawiedliwa_kolejnosc():
    pierwsza, druga = firma(), firma()
    with (
        patch("accounts.tasks_stripe.LIMIT_FIRM", 1),
        patch(
            "stripe.Subscription.retrieve",
            return_value=subskrypcja_stripe(pierwsza, sid=f"sub_{pierwsza.pk}"),
        ),
    ):
        assert uzgodnij_platnosci() == 1
    with patch(
        "stripe.Subscription.retrieve",
        return_value=subskrypcja_stripe(druga, sid=f"sub_{druga.pk}"),
    ):
        assert uzgodnij_platnosci() == 1
    assert KontrolaStripe.objects.filter(uzgodniono_at__isnull=False).count() == 2


def test_budzet_czasu_zostawia_nieruszone_firmy_do_kolejnego_przebiegu():
    firma()
    with patch("accounts.tasks_stripe.monotonic", side_effect=[0, 51]):
        assert uzgodnij_platnosci() == 0
    assert not KontrolaStripe.objects.exists()


def test_dwie_aktywne_subskrypcje_alarm_bez_przelaczenia():
    tenant = firma()
    ProbaZakupu.objects.create(tenant=tenant, sesja_id="cs_test_duplikat")
    with (
        patch(
            "stripe.checkout.Session.retrieve",
            return_value={
                "status": "complete",
                "subscription": "sub_duplikat",
                "metadata": {"tenant_id": str(tenant.pk)},
            },
        ),
        patch(
            "stripe.Subscription.retrieve",
            side_effect=[
                subskrypcja_stripe(tenant, sid=f"sub_{tenant.pk}"),
                subskrypcja_stripe(tenant, sid="sub_duplikat"),
            ],
        ),
        patch("accounts.tasks_stripe._alarmuj"),
    ):
        uzgodnij_platnosci()
    assert Subscription.objects.get(tenant=tenant).stripe_subscription_id == f"sub_{tenant.pk}"
    assert KontrolaStripe.objects.get(tenant=tenant).blad


def test_zajeta_synchronizacja_wraca_w_nastepnym_przebiegu():
    tenant = firma()
    with patch("accounts.tasks_stripe._uzgodnij_firme", side_effect=SynchronizacjaZajeta):
        uzgodnij_platnosci()
    kontrola = KontrolaStripe.objects.get(tenant=tenant)
    assert kontrola.probowano_at is None and not kontrola.blad
    with patch(
        "stripe.Subscription.retrieve",
        return_value=subskrypcja_stripe(tenant, sid=f"sub_{tenant.pk}"),
    ):
        assert uzgodnij_platnosci() == 1


def test_raport_domyslnie_nie_wola_stripe_i_wykrywa_brak_kontroli():
    firma()
    with patch("stripe.Subscription.retrieve") as retrieve:
        call_command("kontrola_stripe")
        with pytest.raises(CommandError):
            call_command("kontrola_stripe", check=True)
        retrieve.assert_not_called()


def test_raport_po_sukcesie_i_po_uplywie_doby():
    tenant = firma()
    kontrola = KontrolaStripe.objects.create(tenant=tenant, uzgodniono_at=timezone.now())
    call_command("kontrola_stripe", check=True)
    kontrola.uzgodniono_at -= timedelta(days=2)
    kontrola.save()
    with pytest.raises(CommandError):
        call_command("kontrola_stripe", check=True)


def test_uzgodnienie_reczne_wymaga_wskazania_firmy():
    with pytest.raises(CommandError):
        call_command("kontrola_stripe", uzgodnij=True)


def test_cudza_sesja_nie_jest_uzgadniana():
    tenant = firma()
    ProbaZakupu.objects.create(tenant=tenant, sesja_id="cs_test_cudza")
    with (
        patch(
            "stripe.checkout.Session.retrieve",
            return_value={
                "status": "complete",
                "subscription": "sub_obca",
                "metadata": {"tenant_id": "999999"},
            },
        ),
        patch(
            "stripe.Subscription.retrieve",
            return_value=subskrypcja_stripe(tenant, sid=f"sub_{tenant.pk}"),
        ) as retrieve,
        patch("accounts.tasks_stripe._alarmuj"),
    ):
        uzgodnij_platnosci()
        retrieve.assert_called_once_with(f"sub_{tenant.pk}", expand=["schedule"])
    assert KontrolaStripe.objects.get(tenant=tenant).blad
