"""
Stan subskrypcji w panelu po zmianach zaplanowanych w Stripe.

Znalezione przy odbiorze F11 części 2 (14.09.2026, tryb testowy Stripe):

* anulowanie z końcem okresu - panel pokazywał zwykły aktywny plan z datą
  o trzy dni za późną, a alert końca był wyłączony,
* obniżka od następnego okresu - panel bez słowa o zmianie,
* anulowany plan oznaczony jako „obecny" - nie dało się go kupić ponownie,
* firma bez aktywnego planu dostawała 429 na ekranie płatności.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core import mail

from accounts.models import Subscription, Tenant
from accounts.tasks_konce import sprawdz_konce_subskrypcji
from api.tests.test_platnosci_portal import ceny, firma, firma_probna, klient  # noqa: F401
from api.tests.test_platnosci_spojnosc import DZIS, subskrypcja_stripe, wyslij, znacznik
from api.views.stripe_webhook import pobierz_subskrypcje

PLANY = "/api/billing/plans/"
KONIEC_OKRESU = DZIS + timedelta(days=20)


def pro(tenant, **pola):
    """Opłacana subskrypcja Pro firmy, okres kończy się za 20 dni."""
    return {
        **subskrypcja_stripe(
            tenant, sid="sub_1", plan="pro", cena="price_pro", koniec=KONIEC_OKRESU
        ),
        **pola,
    }


def harmonogram_obnizki(na="price_grow"):
    return {
        "id": "sub_sched_1",
        "object": "subscription_schedule",
        "current_phase": {"start_date": znacznik(DZIS), "end_date": znacznik(KONIEC_OKRESU)},
        "phases": [
            {
                "start_date": znacznik(DZIS),
                "end_date": znacznik(KONIEC_OKRESU),
                "items": [{"price": "price_pro", "quantity": 1}],
            },
            {
                "start_date": znacznik(KONIEC_OKRESU),
                "end_date": None,
                "items": [{"price": na, "quantity": 1}],
            },
        ],
        "end_behavior": "release",
    }


def zdarzenie(tenant, obiekt):
    return wyslij("customer.subscription.updated", obiekt, {"sub_1": obiekt})


def stan(tenant):
    return Subscription.objects.get(tenant=tenant)


@pytest.mark.django_db
class TestAnulowania:
    def test_anulowanie_z_koncem_okresu_konczy_dostep_w_dniu_anulowania(self, firma):
        zdarzenie(firma, pro(firma, cancel_at=znacznik(KONIEC_OKRESU)))

        s = stan(firma)
        assert s.is_active is True
        assert s.anulowanie_od == KONIEC_OKRESU
        # Bez trzech dni zapasu - po anulowaniu płatności już nie będzie
        assert s.end_date == KONIEC_OKRESU

    def test_samo_cancel_at_period_end_tez_jest_anulowaniem(self, firma):
        zdarzenie(firma, pro(firma, cancel_at=None, cancel_at_period_end=True))

        assert stan(firma).anulowanie_od == KONIEC_OKRESU

    def test_cofniecie_anulowania_przywraca_odnowienie(self, firma):
        zdarzenie(firma, pro(firma, cancel_at=znacznik(KONIEC_OKRESU)))
        zdarzenie(firma, pro(firma, cancel_at=None, cancel_at_period_end=False))

        s = stan(firma)
        assert s.anulowanie_od is None
        assert s.end_date == KONIEC_OKRESU + timedelta(days=3)

    def test_zakonczona_subskrypcja_nie_niesie_starych_zmian(self, firma):
        zdarzenie(
            firma,
            pro(firma, cancel_at=znacznik(KONIEC_OKRESU), schedule=harmonogram_obnizki()),
        )
        zdarzenie(firma, pro(firma, status="canceled"))

        s = stan(firma)
        assert (s.is_active, s.anulowanie_od, s.zaplanowany_plan, s.zaplanowany_plan_od) == (
            False,
            None,
            "",
            None,
        )

    def test_anulowana_subskrypcja_dostaje_alert_konca(self, firma):
        # Alert końca był wyłączony dla każdej aktywnej subskrypcji Stripe -
        # także takiej, która się nie odnowi.
        koniec = DZIS + timedelta(days=3)
        Subscription.objects.filter(tenant=firma).update(
            end_date=koniec, anulowanie_od=koniec, stripe_status="active"
        )

        assert sprawdz_konce_subskrypcji() == 1
        assert "3 dni" in mail.outbox[0].subject


@pytest.mark.django_db
class TestZaplanowanejZmiany:
    def test_obnizka_z_portalu_jest_zapisana(self, firma):
        zdarzenie(firma, pro(firma, schedule=harmonogram_obnizki()))

        s = stan(firma)
        assert s.plan_type == "pro"
        assert (s.zaplanowany_plan, s.zaplanowany_plan_od) == ("grow", KONIEC_OKRESU)
        # Obniżka nie skraca dostępu
        assert s.anulowanie_od is None
        assert s.end_date == KONIEC_OKRESU + timedelta(days=3)

    def test_zmiana_wchodzi_i_harmonogram_znika(self, firma):
        zdarzenie(firma, pro(firma, schedule=harmonogram_obnizki()))
        zdarzenie(
            firma,
            {
                **subskrypcja_stripe(firma, sid="sub_1", plan="grow", cena="price_grow"),
                "schedule": None,
            },
        )

        s = stan(firma)
        assert (s.plan_type, s.zaplanowany_plan, s.zaplanowany_plan_od) == ("grow", "", None)

    def test_harmonogram_bez_zmiany_planu_niczego_nie_zapowiada(self, firma):
        zdarzenie(firma, pro(firma, schedule=harmonogram_obnizki(na="price_pro")))

        assert stan(firma).zaplanowany_plan == ""

    def test_harmonogram_pobierany_razem_z_subskrypcja(self):
        # Jedno zapytanie: zaplanowana obniżka jest tylko w harmonogramie.
        with patch("stripe.Subscription.retrieve", return_value={"id": "sub_1"}) as pobierz:
            pobierz_subskrypcje("sub_1")

        assert pobierz.call_args.kwargs.get("expand") == ["schedule"]


@pytest.mark.django_db
class TestPrzegladu:
    def test_panel_dostaje_anulowanie_i_zaplanowany_plan(self, firma):
        Subscription.objects.filter(tenant=firma).update(
            plan_type="pro",
            anulowanie_od=KONIEC_OKRESU,
            zaplanowany_plan="grow",
            zaplanowany_plan_od=KONIEC_OKRESU,
        )
        # Firma z fixture pamięta subskrypcję z chwili utworzenia
        firma.refresh_from_db()

        biezacy = klient(firma).get(PLANY).json()["current"]

        assert biezacy["cancel_at"] == KONIEC_OKRESU.isoformat()
        assert biezacy["scheduled_plan"] == "grow"
        assert biezacy["scheduled_plan_name"] == "Grow"
        assert biezacy["scheduled_plan_from"] == KONIEC_OKRESU.isoformat()

    def test_bez_zmian_pola_sa_puste(self, firma):
        biezacy = klient(firma).get(PLANY).json()["current"]

        assert (biezacy["cancel_at"], biezacy["scheduled_plan"]) == (None, None)

    def test_anulowany_plan_nie_jest_obecnym_i_da_sie_go_kupic(self, firma):
        # Przy odbiorze: po anulowaniu Grow był „Twoim obecnym planem" bez
        # przycisku, więc nie dało się wznowić tego samego planu.
        Subscription.objects.filter(tenant=firma).update(is_active=False, stripe_status="canceled")
        firma.refresh_from_db()

        plany = klient(firma).get(PLANY).json()["plans"]

        assert [p["code"] for p in plany if p["current"]] == []

    def test_aktywny_plan_pozostaje_obecnym(self, firma):
        plany = klient(firma).get(PLANY).json()["plans"]

        assert [p["code"] for p in plany if p["current"]] == ["grow"]


@pytest.mark.django_db
def test_firma_bez_aktywnego_planu_moze_przegladac_platnosci(firma):
    # Firma bez aktywnej subskrypcji ma najniższą stawkę czatu: 30 zapytań na
    # minutę na cały panel. Ekran płatności dostawał 429 po kilku kliknięciach -
    # właśnie wtedy, gdy klient przyszedł zapłacić.
    Subscription.objects.filter(tenant=firma).update(is_active=False, stripe_status="canceled")
    wlasciciel = klient(firma)

    kody = [wlasciciel.get(PLANY).status_code for _ in range(40)]

    assert set(kody) == {200}
    assert Tenant.objects.filter(pk=firma.pk).exists()
