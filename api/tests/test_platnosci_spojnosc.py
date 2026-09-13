"""
F11, część 1 - spójność płatności ze Stripe.

Każdy przypadek odtwarza stan, w którym baza mówiła co innego niż Stripe:
dostęp bez zapłaty, odcięcie opłaconego klienta albo podwójne obciążenie.
Opis i wyniki na starym kodzie: docs/platnosci-spojnosc.md.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from threading import Barrier
from unittest.mock import MagicMock, patch

import pytest
import stripe
from django.db import close_old_connections, connections
from rest_framework.test import APIClient

from accounts.models import Subscription, Tenant

WEBHOOK = "/api/billing/webhook/"
CHECKOUT = "/api/billing/create-checkout-session/"
DZIS = date.today()


def znacznik(dzien):
    return int(datetime(dzien.year, dzien.month, dzien.day, 12, tzinfo=UTC).timestamp())


def subskrypcja_stripe(
    tenant, sid="sub_1", status="active", poczatek=None, koniec=None, plan="pro", cena=None
):
    poczatek = poczatek or DZIS - timedelta(days=1)
    koniec = koniec or DZIS + timedelta(days=30)
    return {
        "id": sid,
        "object": "subscription",
        "status": status,
        "current_period_start": znacznik(poczatek),
        "current_period_end": znacznik(koniec),
        "metadata": {"tenant_id": str(tenant.id), "plan": plan},
        "items": {"data": [{"price": {"id": cena or f"price_{plan}"}}]},
    }


def sesja(tenant, sid="sub_1", plan="pro", payment_status="paid"):
    return {
        "object": "checkout.session",
        "subscription": sid,
        "payment_status": payment_status,
        "metadata": {"tenant_id": str(tenant.id), "plan": plan},
    }


def faktura(tenant, sid="sub_1", plan="pro"):
    return {
        "object": "invoice",
        "metadata": {},
        "parent": {
            "subscription_details": {
                "subscription": sid,
                "metadata": {"tenant_id": str(tenant.id), "plan": plan},
            }
        },
    }


def wyslij(typ, obiekt, w_stripe):
    """`w_stripe`: identyfikator -> obiekt subskrypcji albo wyjątek ze Stripe."""

    def retrieve(identyfikator, *args, **kwargs):
        wynik = w_stripe[identyfikator]
        if isinstance(wynik, Exception):
            raise wynik
        return wynik

    zdarzenie = {"id": f"evt_{typ}", "type": typ, "data": {"object": obiekt}}
    with (
        patch("stripe.Webhook.construct_event", return_value=zdarzenie),
        patch("stripe.Subscription.retrieve", side_effect=retrieve),
    ):
        return APIClient().post(
            WEBHOOK, data="{}", content_type="application/json", HTTP_STRIPE_SIGNATURE="podpis"
        )


@pytest.fixture
def ceny(settings):
    settings.STRIPE_PRICE_IDS = {"start": "price_start", "grow": "price_grow", "pro": "price_pro"}
    settings.STRIPE_PRICE_IDS_ROCZNE = {"pro": "price_pro_roczny"}


@pytest.fixture
def firma(db, ceny):
    """Firma w okresie próbnym - bez żadnego wiązania ze Stripe."""
    tenant = Tenant.objects.create(name="Salon Aurora", owner_email="a@firma.pl")
    Subscription.objects.create(
        tenant=tenant,
        plan_type="trial",
        is_active=True,
        message_limit=500,
        start_date=DZIS - timedelta(days=3),
        end_date=DZIS + timedelta(days=11),
    )
    return tenant


def stan(tenant):
    return Subscription.objects.get(tenant=tenant)


@pytest.mark.django_db
class TestZakupu:
    def test_okres_pochodzi_ze_stripe(self, firma):
        # Na starym kodzie: zawsze dziś + 31 dni.
        koniec = DZIS + timedelta(days=30)
        sub = subskrypcja_stripe(firma, koniec=koniec)
        assert wyslij("checkout.session.completed", sesja(firma), {"sub_1": sub}).status_code == 200
        subskrypcja = stan(firma)
        assert subskrypcja.plan_type == "pro"
        assert subskrypcja.is_active is True
        assert subskrypcja.end_date == koniec + timedelta(days=3)
        assert subskrypcja.stripe_subscription_id == "sub_1"

    def test_plan_roczny_ma_roczny_okres(self, firma):
        koniec = DZIS + timedelta(days=365)
        sub = subskrypcja_stripe(firma, koniec=koniec, cena="price_pro_roczny", plan="")
        wyslij("checkout.session.completed", sesja(firma, plan=""), {"sub_1": sub})
        assert stan(firma).end_date == koniec + timedelta(days=3)
        assert stan(firma).plan_type == "pro"

    def test_sesja_bez_zaplaty_nie_aktywuje_planu(self, firma):
        # Na starym kodzie `checkout.session.completed` aktywował plan bez
        # sprawdzenia, czy płatność przeszła.
        sub = subskrypcja_stripe(firma, status="incomplete")
        wyslij("checkout.session.completed", sesja(firma, payment_status="unpaid"), {"sub_1": sub})
        assert stan(firma).plan_type == "trial"
        assert stan(firma).stripe_subscription_id == ""


@pytest.mark.django_db
class TestKolejnosciIPowtorzen:
    def test_powtorka_starego_zakupu_po_anulowaniu_nie_przywraca_dostepu(self, firma):
        # Stripe ponawia zdarzenia do trzech dni. Na starym kodzie powtórzony
        # zakup po anulowaniu dawał kolejne 31 dni bez płatności.
        aktywna = subskrypcja_stripe(firma)
        wyslij("checkout.session.completed", sesja(firma), {"sub_1": aktywna})
        anulowana = {**aktywna, "status": "canceled"}
        wyslij("customer.subscription.deleted", anulowana, {"sub_1": anulowana})
        wyslij("checkout.session.completed", sesja(firma), {"sub_1": anulowana})
        assert stan(firma).is_active is False

    def test_spozniona_nieudana_platnosc_nie_odcina_oplaconego_klienta(self, firma):
        aktywna = subskrypcja_stripe(firma)
        wyslij("invoice.payment_succeeded", faktura(firma), {"sub_1": aktywna})
        # Zdarzenie z wcześniejszej, nieudanej próby dociera po udanej.
        wyslij("invoice.payment_failed", faktura(firma), {"sub_1": aktywna})
        assert stan(firma).is_active is True

    def test_duplikat_zdarzenia_daje_ten_sam_stan(self, firma):
        """Straż: dwa razy to samo zdarzenie, jeden wiersz, ten sam okres."""
        aktywna = subskrypcja_stripe(firma)
        wyslij("checkout.session.completed", sesja(firma), {"sub_1": aktywna})
        pierwszy = stan(firma).end_date
        wyslij("checkout.session.completed", sesja(firma), {"sub_1": aktywna})
        assert Subscription.objects.filter(tenant=firma).count() == 1
        assert stan(firma).end_date == pierwszy


@pytest.mark.django_db
class TestNieudanychPlatnosci:
    def test_nieudane_odnowienie_zostawia_oplacony_okres_z_buforem(self, firma):
        # Na starym kodzie pierwsza nieudana próba odcinała czat od razu.
        poczatek = DZIS - timedelta(days=1)
        wyslij("invoice.payment_succeeded", faktura(firma), {"sub_1": subskrypcja_stripe(firma)})
        zalegla = subskrypcja_stripe(firma, status="past_due", poczatek=poczatek)
        wyslij("invoice.payment_failed", faktura(firma), {"sub_1": zalegla})
        subskrypcja = stan(firma)
        assert subskrypcja.is_active is True
        # Koniec OPŁACONEGO okresu, nie nowego, za który płatność nie przeszła.
        assert subskrypcja.end_date == poczatek + timedelta(days=3)
        firma.refresh_from_db()
        assert firma.subscription_status == "past_due"

    def test_brak_zaplaty_po_ponowieniach_odcina_dostep(self, firma):
        wyslij("invoice.payment_succeeded", faktura(firma), {"sub_1": subskrypcja_stripe(firma)})
        nieoplacona = subskrypcja_stripe(firma, status="unpaid")
        wyslij("customer.subscription.updated", nieoplacona, {"sub_1": nieoplacona})
        assert stan(firma).is_active is False
        firma.refresh_from_db()
        assert firma.subscription_status == "suspended"


@pytest.mark.django_db
class TestIdentyfikatorowStripe:
    def test_usuniecie_starej_subskrypcji_nie_zawiesza_nowej(self, firma):
        nowa = subskrypcja_stripe(firma, sid="sub_nowa")
        wyslij("checkout.session.completed", sesja(firma, sid="sub_nowa"), {"sub_nowa": nowa})
        stara = subskrypcja_stripe(firma, sid="sub_stara", status="canceled")
        wyslij("customer.subscription.deleted", stara, {"sub_stara": stara})
        assert stan(firma).is_active is True
        assert stan(firma).stripe_subscription_id == "sub_nowa"

    def test_zmiana_planu_w_stripe_zmienia_limit(self, firma):
        # Metadane zostają "pro", ale klient płaci już za Grow.
        wyslij("checkout.session.completed", sesja(firma), {"sub_1": subskrypcja_stripe(firma)})
        zmieniona = subskrypcja_stripe(firma, plan="pro", cena="price_grow")
        wyslij("customer.subscription.updated", zmieniona, {"sub_1": zmieniona})
        assert stan(firma).plan_type == "grow"


@pytest.mark.django_db
class TestAwariiStripe:
    def test_przejsciowa_awaria_to_500_do_ponowienia(self, firma):
        # Na starym kodzie awaria przy fakturze kończyła się 200 i zdarzenie
        # przepadało - Stripe nie miał powodu go ponawiać.
        awaria = stripe.error.APIConnectionError("Stripe nie odpowiada")
        odpowiedz = wyslij("invoice.payment_succeeded", faktura(firma), {"sub_1": awaria})
        assert odpowiedz.status_code == 500
        assert stan(firma).plan_type == "trial"

    def test_nieistniejaca_subskrypcja_to_200_bez_zmian(self, firma):
        brak = stripe.error.InvalidRequestError("No such subscription: sub_1", "id")
        odpowiedz = wyslij("invoice.payment_succeeded", faktura(firma), {"sub_1": brak})
        assert odpowiedz.status_code == 200
        assert stan(firma).plan_type == "trial"


@pytest.mark.django_db(transaction=True)
def test_dwa_zdarzenia_zakupu_naraz_zakladaja_jeden_wiersz(ceny):
    """Zakup wysyła dwa zdarzenia w tej samej sekundzie; firma bez subskrypcji."""
    tenant = Tenant.objects.create(name="Nowa firma", owner_email="n@firma.pl")
    aktywna = subskrypcja_stripe(tenant)
    bramka = Barrier(2)

    def jedno(typ):
        close_old_connections()
        try:
            bramka.wait(timeout=5)
            obiekt = sesja(tenant) if typ.startswith("checkout") else faktura(tenant)
            return APIClient().post(
                WEBHOOK, data="{}", content_type="application/json", HTTP_STRIPE_SIGNATURE="p"
            ).status_code, obiekt
        finally:
            connections.close_all()

    zdarzenia = {
        "checkout": {"type": "checkout.session.completed", "data": {"object": sesja(tenant)}},
        "invoice": {"type": "invoice.payment_succeeded", "data": {"object": faktura(tenant)}},
    }
    with (
        patch(
            "stripe.Webhook.construct_event",
            side_effect=[zdarzenia["checkout"], zdarzenia["invoice"]],
        ),
        patch("stripe.Subscription.retrieve", return_value=aktywna),
        ThreadPoolExecutor(max_workers=2) as pula,
    ):
        wyniki = list(pula.map(jedno, ["checkout", "invoice"]))

    assert [kod for kod, _ in wyniki] == [200, 200]
    assert Subscription.objects.filter(tenant=tenant).count() == 1


def wlasciciel(user, tenant):
    user.tenant, user.role = tenant, "owner"
    user.save()
    klient = APIClient()
    klient.force_authenticate(user=user)
    klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))
    return klient


@pytest.fixture
def stripe_checkout():
    with (
        patch("api.views.stripe.kartoteka_klienta", return_value="cus_1"),
        patch(
            "stripe.checkout.Session.create",
            return_value=MagicMock(url="https://checkout.stripe.test/s"),
        ) as utworz,
    ):
        yield utworz


@pytest.mark.django_db
class TestCheckoutu:
    def test_drugi_zakup_przy_aktywnej_subskrypcji_jest_odrzucony(
        self, user, firma, stripe_checkout
    ):
        # Na starym kodzie powstawała druga subskrypcja w Stripe - dwa obciążenia
        # miesięcznie za jedno konto.
        Subscription.objects.filter(tenant=firma).update(
            plan_type="pro", stripe_subscription_id="sub_1", stripe_status="active"
        )
        odpowiedz = wlasciciel(user, firma).post(CHECKOUT, {"plan_type": "grow"}, format="json")
        assert odpowiedz.status_code == 400
        stripe_checkout.assert_not_called()

    def test_okres_probny_moze_kupic_plan(self, user, firma, stripe_checkout):
        """Straż: blokada dotyczy wyłącznie aktywnej subskrypcji w Stripe."""
        odpowiedz = wlasciciel(user, firma).post(CHECKOUT, {"plan_type": "pro"}, format="json")
        assert odpowiedz.status_code == 200
        stripe_checkout.assert_called_once()

    def test_anulowana_subskrypcja_nie_blokuje_zakupu(self, user, firma, stripe_checkout):
        Subscription.objects.filter(tenant=firma).update(
            is_active=False, stripe_subscription_id="sub_1", stripe_status="canceled"
        )
        odpowiedz = wlasciciel(user, firma).post(CHECKOUT, {"plan_type": "pro"}, format="json")
        assert odpowiedz.status_code == 200

    def test_podwojne_klikniecie_prowadzi_do_tej_samej_sesji(self, user, firma, stripe_checkout):
        # Klucz idempotencji: Stripe zwraca tę samą sesję zamiast drugiej,
        # którą dałoby się opłacić osobno.
        klient = wlasciciel(user, firma)
        klient.post(CHECKOUT, {"plan_type": "pro"}, format="json")
        klient.post(CHECKOUT, {"plan_type": "pro"}, format="json")
        klucze = [
            wywolanie.kwargs.get("idempotency_key") for wywolanie in stripe_checkout.call_args_list
        ]
        assert len(klucze) == 2 and klucze[0] and klucze[0] == klucze[1]
        assert str(firma.id) in klucze[0] and "pro" in klucze[0]
