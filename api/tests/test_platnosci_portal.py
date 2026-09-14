"""
F11, część 2: zmiana planu w portalu Stripe, zakup tylko przez właściciela,
potwierdzenie konkretnej płatności i powiadomienie o nieudanej płatności.

Żaden test nie łączy się ze Stripe (conftest.zadne_polaczenie_ze_stripe) -
każde wywołanie jest podstawione.
"""

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import stripe
from django.core import mail
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.models import CustomUser, Subscription, Tenant
from api.tests.test_platnosci_spojnosc import faktura, subskrypcja_stripe, wyslij
from api.utils.stripe_portal import ZNACZNIK, oznaczenie_konfiguracji

DZIS = date.today()
PLANY = "/api/billing/plans/"
CHECKOUT = "/api/billing/create-checkout-session/"
PORTAL = "/api/billing/portal/"
SESJA = "cs_test_a1b2c3d4e5f6"


def stan_zakupu_url(identyfikator=SESJA):
    return f"/api/billing/checkout-session/{identyfikator}/"


@pytest.fixture(autouse=True)
def czysta_pamiec():
    # Konfiguracja portalu jest zapamiętywana - bez tego testy widziałyby
    # identyfikator z poprzedniego testu.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def ceny(settings):
    settings.STRIPE_PRICE_IDS = {"start": "price_start", "grow": "price_grow", "pro": "price_pro"}
    settings.STRIPE_PRICE_IDS_ROCZNE = {}


@pytest.fixture
def firma(db, ceny):
    """Firma z opłacaną subskrypcją Grow w Stripe."""
    tenant = Tenant.objects.create(
        name="Salon Aurora", owner_email="wlasciciel@firma.pl", stripe_customer_id="cus_1"
    )
    Subscription.objects.create(
        tenant=tenant,
        plan_type="grow",
        is_active=True,
        message_limit=8_000,
        start_date=DZIS - timedelta(days=5),
        end_date=DZIS + timedelta(days=28),
        stripe_subscription_id="sub_1",
        stripe_status="active",
    )
    return tenant


@pytest.fixture
def firma_probna(db, ceny):
    """Firma w okresie próbnym - bez subskrypcji Stripe."""
    tenant = Tenant.objects.create(name="Kwiaciarnia", owner_email="kwiaty@firma.pl")
    Subscription.objects.create(
        tenant=tenant,
        plan_type="trial",
        is_active=True,
        message_limit=500,
        start_date=DZIS - timedelta(days=3),
        end_date=DZIS + timedelta(days=11),
    )
    return tenant


def klient(tenant, rola="owner"):
    uzytkownik = CustomUser.objects.create_user(
        username=f"{rola}-{tenant.id}",
        email=f"{rola}-{tenant.id}@firma.pl",
        password="haslo-testowe-123",
        tenant=tenant,
    )
    uzytkownik.role = rola
    uzytkownik.save()
    wynik = APIClient()
    wynik.force_authenticate(user=uzytkownik)
    wynik.credentials(HTTP_X_API_KEY=str(tenant.api_key))
    return wynik


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


@pytest.fixture
def stripe_portal():
    konfiguracje = MagicMock()
    konfiguracje.auto_paging_iter.return_value = []
    with (
        patch(
            "stripe.Price.retrieve",
            side_effect=lambda cena, *a, **k: {"id": cena, "product": f"prod_{cena}"},
        ),
        patch("stripe.billing_portal.Configuration.list", return_value=konfiguracje) as lista,
        patch(
            "stripe.billing_portal.Configuration.create", return_value={"id": "bpc_1"}
        ) as utworz_konfiguracje,
        patch(
            "stripe.billing_portal.Session.create",
            return_value=MagicMock(url="https://billing.stripe.test/p"),
        ) as sesja,
        patch(
            "stripe.Subscription.retrieve",
            return_value={
                "id": "sub_1",
                "items": {"data": [{"id": "si_1", "price": {"id": "price_grow"}}]},
            },
        ) as subskrypcja,
    ):
        yield SimpleNamespace(
            lista=lista,
            konfiguracje=konfiguracje,
            utworz_konfiguracje=utworz_konfiguracje,
            sesja=sesja,
            subskrypcja=subskrypcja,
        )


@pytest.mark.django_db
class TestUprawnien:
    @pytest.mark.parametrize("rola", ["employee", "viewer"])
    def test_zakup_planu_tylko_dla_wlasciciela(self, firma_probna, stripe_checkout, rola):
        # Na starym kodzie wystarczało zalogowanie: plan (i obciążenie karty
        # firmy) mógł uruchomić pracownik albo konto tylko do podglądu.
        odpowiedz = klient(firma_probna, rola).post(CHECKOUT, {"plan_type": "pro"}, format="json")
        assert odpowiedz.status_code == 403
        stripe_checkout.assert_not_called()

    def test_wlasciciel_kupuje_plan(self, firma_probna, stripe_checkout):
        odpowiedz = klient(firma_probna).post(CHECKOUT, {"plan_type": "pro"}, format="json")
        assert odpowiedz.status_code == 200
        stripe_checkout.assert_called_once()

    @pytest.mark.parametrize("rola", ["employee", "viewer"])
    def test_portal_tylko_dla_wlasciciela(self, firma, stripe_portal, rola):
        odpowiedz = klient(firma, rola).post(PORTAL, {"plan_type": "pro"}, format="json")
        assert odpowiedz.status_code == 403
        stripe_portal.sesja.assert_not_called()


@pytest.mark.django_db
def test_odmowa_zakupu_to_jedno_zdanie_a_nie_lista(firma, stripe_checkout):
    # Panel pokazywał klientowi dosłownie ["Masz już aktywną subskrypcję..."].
    odpowiedz = klient(firma).post(CHECKOUT, {"plan_type": "pro"}, format="json")
    assert odpowiedz.status_code == 400
    tresc = odpowiedz.json()
    assert isinstance(tresc, dict) and isinstance(tresc.get("detail"), str)
    assert tresc["detail"].startswith("Masz już aktywną subskrypcję (Grow)")


@pytest.mark.django_db
class TestZmianyPlanu:
    def test_zmiana_planu_na_tej_samej_subskrypcji(self, firma, stripe_portal, stripe_checkout):
        odpowiedz = klient(firma).post(PORTAL, {"plan_type": "pro"}, format="json")

        assert odpowiedz.status_code == 200
        assert odpowiedz.json() == {"portal_url": "https://billing.stripe.test/p"}
        parametry = stripe_portal.sesja.call_args.kwargs
        assert parametry["customer"] == "cus_1"
        assert parametry["configuration"] == "bpc_1"
        assert parametry["locale"] == "pl"
        przebieg = parametry["flow_data"]
        assert przebieg["type"] == "subscription_update_confirm"
        assert przebieg["subscription_update_confirm"] == {
            "subscription": "sub_1",
            "items": [{"id": "si_1", "price": "price_pro", "quantity": 1}],
        }
        assert przebieg["after_completion"]["redirect"]["return_url"].endswith(
            "/subskrypcja?zmiana=1"
        )
        # Żadnej nowej subskrypcji
        stripe_checkout.assert_not_called()

    def test_bez_planu_portal_otwiera_karte_i_faktury(self, firma, stripe_portal):
        odpowiedz = klient(firma).post(PORTAL, {}, format="json")

        assert odpowiedz.status_code == 200
        assert "flow_data" not in stripe_portal.sesja.call_args.kwargs
        stripe_portal.subskrypcja.assert_not_called()

    def test_obecny_plan_jest_odrzucony(self, firma, stripe_portal):
        odpowiedz = klient(firma).post(PORTAL, {"plan_type": "grow"}, format="json")

        assert odpowiedz.status_code == 400
        assert odpowiedz.json() == {"detail": "Grow to Twój obecny plan."}
        stripe_portal.sesja.assert_not_called()

    def test_zmiana_planu_wymaga_aktywnej_subskrypcji(self, firma, stripe_portal):
        Subscription.objects.filter(tenant=firma).update(is_active=False, stripe_status="canceled")

        odpowiedz = klient(firma).post(PORTAL, {"plan_type": "pro"}, format="json")

        assert odpowiedz.status_code == 400
        stripe_portal.sesja.assert_not_called()

    def test_nieznany_plan(self, firma, stripe_portal):
        odpowiedz = klient(firma).post(PORTAL, {"plan_type": "zloty"}, format="json")

        assert odpowiedz.status_code == 400
        stripe_portal.sesja.assert_not_called()

    def test_firma_bez_kartoteki_stripe(self, firma_probna, stripe_portal):
        odpowiedz = klient(firma_probna).post(PORTAL, {}, format="json")

        assert odpowiedz.status_code == 400
        assert "Wybierz plan" in odpowiedz.json()["detail"]
        stripe_portal.sesja.assert_not_called()

    def test_subskrypcja_z_kilkoma_pozycjami_nie_jest_zmieniana(self, firma, stripe_portal):
        stripe_portal.subskrypcja.return_value = {
            "id": "sub_1",
            "items": {
                "data": [
                    {"id": "si_1", "price": {"id": "price_grow"}},
                    {"id": "si_2", "price": {"id": "price_dodatek"}},
                ]
            },
        }

        odpowiedz = klient(firma).post(PORTAL, {"plan_type": "pro"}, format="json")

        assert odpowiedz.status_code == 400
        stripe_portal.sesja.assert_not_called()

    def test_blad_stripe_daje_czytelna_odmowe(self, firma, stripe_portal):
        stripe_portal.sesja.side_effect = stripe.error.APIConnectionError("brak sieci")

        odpowiedz = klient(firma).post(PORTAL, {"plan_type": "pro"}, format="json")

        assert odpowiedz.status_code == 400
        assert odpowiedz.json()["detail"].startswith("Nie udało się otworzyć")


@pytest.mark.django_db
class TestKonfiguracjiPortalu:
    def test_konfiguracja_zgodna_z_decyzja_wlasciciela(self, firma, stripe_portal):
        klient(firma).post(PORTAL, {}, format="json")

        parametry = stripe_portal.utworz_konfiguracje.call_args.kwargs
        funkcje = parametry["features"]
        zmiana = funkcje["subscription_update"]
        # Wyższy plan od razu, z fakturą na różnicę
        assert zmiana["proration_behavior"] == "always_invoice"
        # Niższy plan od następnego okresu
        assert {"type": "decreasing_item_amount"} in zmiana["schedule_at_period_end"]["conditions"]
        assert zmiana["default_allowed_updates"] == ["price"]
        assert sorted(c for p in zmiana["products"] for c in p["prices"]) == [
            "price_grow",
            "price_pro",
            "price_start",
        ]
        assert funkcje["subscription_cancel"]["mode"] == "at_period_end"
        # Dane do faktury tylko w panelu
        assert funkcje["customer_update"] == {"enabled": False}
        assert funkcje["payment_method_update"] == {"enabled": True}
        assert parametry["metadata"] == {ZNACZNIK: oznaczenie_konfiguracji()}
        assert parametry["idempotency_key"]

    def test_konfiguracja_zakladana_raz(self, firma, stripe_portal):
        wlasciciel = klient(firma)
        wlasciciel.post(PORTAL, {}, format="json")
        wlasciciel.post(PORTAL, {}, format="json")

        stripe_portal.utworz_konfiguracje.assert_called_once()

    def test_istniejaca_konfiguracja_jest_uzywana(self, firma, stripe_portal):
        stripe_portal.konfiguracje.auto_paging_iter.return_value = [
            {"id": "bpc_stara", "metadata": {ZNACZNIK: "0-nieaktualna"}},
            {"id": "bpc_biezaca", "metadata": {ZNACZNIK: oznaczenie_konfiguracji()}},
        ]

        klient(firma).post(PORTAL, {}, format="json")

        stripe_portal.utworz_konfiguracje.assert_not_called()
        assert stripe_portal.sesja.call_args.kwargs["configuration"] == "bpc_biezaca"

    def test_nowa_cena_to_nowa_konfiguracja(self, settings, ceny):
        przed = oznaczenie_konfiguracji()
        settings.STRIPE_PRICE_IDS = {**settings.STRIPE_PRICE_IDS, "pro": "price_pro_2027"}
        assert oznaczenie_konfiguracji() != przed


def sesja_checkout(tenant, status="complete", payment_status="paid", sid="sub_2", plan="pro"):
    return {
        "id": SESJA,
        "object": "checkout.session",
        "status": status,
        "payment_status": payment_status,
        "subscription": sid,
        "metadata": {"tenant_id": str(tenant.id), "plan": plan},
    }


@pytest.mark.django_db
class TestPotwierdzeniaZakupu:
    def test_zakup_potwierdzony_po_webhooku(self, firma_probna):
        Subscription.objects.filter(tenant=firma_probna).update(
            plan_type="pro", stripe_subscription_id="sub_2", stripe_status="active"
        )
        with (
            patch("stripe.checkout.Session.retrieve", return_value=sesja_checkout(firma_probna)),
            patch("stripe.Subscription.retrieve") as pobierz,
        ):
            odpowiedz = klient(firma_probna).get(stan_zakupu_url())

        assert odpowiedz.status_code == 200
        assert odpowiedz.json()["status"] == "aktywna"
        assert odpowiedz.json()["plan_name"] == "Pro"
        pobierz.assert_not_called()

    def test_okres_probny_to_nie_potwierdzenie_zakupu(self, firma_probna):
        # Stara strona sukcesu pytała o ogólny stan planu i firma w okresie
        # próbnym od razu widziała „plan aktywny".
        niedokonczona = subskrypcja_stripe(firma_probna, sid="sub_2", status="incomplete")
        with (
            patch("stripe.checkout.Session.retrieve", return_value=sesja_checkout(firma_probna)),
            patch("stripe.Subscription.retrieve", return_value=niedokonczona),
        ):
            odpowiedz = klient(firma_probna).get(stan_zakupu_url())

        assert odpowiedz.json()["status"] == "w_toku"
        assert Subscription.objects.get(tenant=firma_probna).plan_type == "trial"

    def test_spozniony_webhook_uzgadniany_na_stronie_sukcesu(self, firma_probna):
        aktywna = subskrypcja_stripe(firma_probna, sid="sub_2", plan="pro", cena="price_pro")
        with (
            patch("stripe.checkout.Session.retrieve", return_value=sesja_checkout(firma_probna)),
            patch("stripe.Subscription.retrieve", return_value=aktywna),
        ):
            odpowiedz = klient(firma_probna).get(stan_zakupu_url())

        assert odpowiedz.json()["status"] == "aktywna"
        stan = Subscription.objects.get(tenant=firma_probna)
        assert (stan.plan_type, stan.stripe_subscription_id, stan.is_active) == (
            "pro",
            "sub_2",
            True,
        )
        assert odpowiedz.json()["access_until"] == stan.end_date.isoformat()

    def test_cudza_sesja_wyglada_jak_nieistniejaca(self, firma, firma_probna):
        with (
            patch("stripe.checkout.Session.retrieve", return_value=sesja_checkout(firma)),
            patch("stripe.Subscription.retrieve") as pobierz,
        ):
            odpowiedz = klient(firma_probna).get(stan_zakupu_url())

        assert odpowiedz.status_code == 404
        pobierz.assert_not_called()
        assert Subscription.objects.get(tenant=firma_probna).plan_type == "trial"

    def test_zly_identyfikator_nie_trafia_do_stripe(self, firma_probna):
        with patch("stripe.checkout.Session.retrieve") as pobierz_sesje:
            odpowiedz = klient(firma_probna).get(stan_zakupu_url("sub_cokolwiek"))

        assert odpowiedz.status_code == 404
        pobierz_sesje.assert_not_called()

    def test_nieistniejaca_sesja(self, firma_probna):
        with patch(
            "stripe.checkout.Session.retrieve",
            side_effect=stripe.error.InvalidRequestError("No such session", param="id"),
        ):
            odpowiedz = klient(firma_probna).get(stan_zakupu_url())

        assert odpowiedz.status_code == 404

    def test_wygasla_sesja(self, firma_probna):
        with patch(
            "stripe.checkout.Session.retrieve",
            return_value=sesja_checkout(firma_probna, status="expired", payment_status="unpaid"),
        ):
            odpowiedz = klient(firma_probna).get(stan_zakupu_url())

        assert odpowiedz.json()["status"] == "wygasla"

    def test_platnosc_jeszcze_przetwarzana(self, firma_probna):
        with (
            patch(
                "stripe.checkout.Session.retrieve",
                return_value=sesja_checkout(firma_probna, payment_status="unpaid"),
            ),
            patch("stripe.Subscription.retrieve") as pobierz,
        ):
            odpowiedz = klient(firma_probna).get(stan_zakupu_url())

        assert odpowiedz.json()["status"] == "w_toku"
        pobierz.assert_not_called()

    def test_awaria_stripe_to_503_do_ponowienia(self, firma_probna):
        with patch(
            "stripe.checkout.Session.retrieve",
            side_effect=stripe.error.APIConnectionError("brak sieci"),
        ):
            odpowiedz = klient(firma_probna).get(stan_zakupu_url())

        assert odpowiedz.status_code == 503
        assert isinstance(odpowiedz.json()["detail"], str)

    def test_tylko_wlasciciel(self, firma_probna):
        with patch("stripe.checkout.Session.retrieve") as pobierz_sesje:
            odpowiedz = klient(firma_probna, "employee").get(stan_zakupu_url())

        assert odpowiedz.status_code == 403
        pobierz_sesje.assert_not_called()


def nieudane_odnowienie(tenant):
    """Stripe przesunął okres na nowy, choć płatność za niego nie przeszła."""
    return subskrypcja_stripe(
        tenant,
        sid="sub_1",
        status="past_due",
        plan="grow",
        cena="price_grow",
        poczatek=DZIS,
        koniec=DZIS + timedelta(days=30),
    )


def udane_odnowienie(tenant):
    return subskrypcja_stripe(tenant, sid="sub_1", status="active", plan="grow", cena="price_grow")


@pytest.mark.django_db
class TestPowiadomieniaONieudanejPlatnosci:
    def test_pierwsza_nieudana_proba_wysyla_wiadomosc(
        self, firma, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            odpowiedz = wyslij(
                "invoice.payment_failed", faktura(firma), {"sub_1": nieudane_odnowienie(firma)}
            )

        assert odpowiedz.status_code == 200
        assert len(mail.outbox) == 1
        wiadomosc = mail.outbox[0]
        assert wiadomosc.to == ["wlasciciel@firma.pl"]
        koniec = (DZIS + timedelta(days=3)).strftime("%d.%m.%Y")
        assert koniec in wiadomosc.body
        assert "Grow" in wiadomosc.body
        assert "/subskrypcja" in wiadomosc.body

    def test_powtorzone_zdarzenia_nie_mnoza_wiadomosci(
        self, firma, django_capture_on_commit_callbacks
    ):
        w_stripe = {"sub_1": nieudane_odnowienie(firma)}
        with django_capture_on_commit_callbacks(execute=True):
            wyslij("invoice.payment_failed", faktura(firma), w_stripe)
            wyslij("customer.subscription.updated", w_stripe["sub_1"], w_stripe)
            wyslij("invoice.payment_failed", faktura(firma), w_stripe)

        assert len(mail.outbox) == 1

    def test_kolejna_nieudana_platnosc_po_odzyskaniu(
        self, firma, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            wyslij("invoice.payment_failed", faktura(firma), {"sub_1": nieudane_odnowienie(firma)})
            wyslij("invoice.paid", faktura(firma), {"sub_1": udane_odnowienie(firma)})
            wyslij("invoice.payment_failed", faktura(firma), {"sub_1": nieudane_odnowienie(firma)})

        assert len(mail.outbox) == 2

    def test_udane_odnowienie_nie_wysyla(self, firma, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            wyslij("invoice.paid", faktura(firma), {"sub_1": udane_odnowienie(firma)})

        assert mail.outbox == []

    def test_wiadomosc_dopiero_po_zapisie_stanu(self, firma, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=False) as zlecone:
            wyslij("invoice.payment_failed", faktura(firma), {"sub_1": nieudane_odnowienie(firma)})

        assert mail.outbox == []
        assert len(zlecone) == 1

    def test_brak_adresu_nie_przerywa_webhooka(self, firma, django_capture_on_commit_callbacks):
        Tenant.objects.filter(pk=firma.pk).update(owner_email="")
        with django_capture_on_commit_callbacks(execute=True):
            odpowiedz = wyslij(
                "invoice.payment_failed", faktura(firma), {"sub_1": nieudane_odnowienie(firma)}
            )

        assert odpowiedz.status_code == 200
        assert mail.outbox == []

    def test_nie_wysyla_gdy_ponowiona_platnosc_juz_przeszla(self, firma):
        from accounts.tasks_konce import powiadom_o_nieudanej_platnosci

        stan = Subscription.objects.get(tenant=firma)
        assert powiadom_o_nieudanej_platnosci(stan.pk) is False
        assert mail.outbox == []


@pytest.mark.django_db
class TestPrzegladuPlanu:
    def test_panel_wie_ze_plan_zmienia_sie_w_portalu(self, firma):
        biezacy = klient(firma).get(PLANY).json()["current"]

        assert biezacy["has_stripe_subscription"] is True
        assert biezacy["portal_available"] is True
        assert biezacy["can_manage"] is True
        assert biezacy["stripe_status"] == "active"
        assert biezacy["access_until"] == (DZIS + timedelta(days=28)).isoformat()

    def test_okres_probny_kupuje_przez_checkout(self, firma_probna):
        biezacy = klient(firma_probna).get(PLANY).json()["current"]

        assert biezacy["has_stripe_subscription"] is False
        assert biezacy["portal_available"] is False

    def test_pracownik_nie_zarzadza_planem(self, firma):
        assert klient(firma, "employee").get(PLANY).json()["current"]["can_manage"] is False
