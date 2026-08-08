"""
Ścieżka płatności: checkout, webhook i uprawnienia planów.

Ta ścieżka nigdy nie zadziałała od początku do końca. Webhook nie był podpięty
pod żaden URL, więc Stripe nie miał dokąd wysyłać zdarzeń. A nawet gdyby był,
aktualizował pola na modelu Tenant, podczas gdy limity wiadomości egzekwuje
SubscriptionMiddleware na podstawie modelu Subscription — klient mógł zapłacić
i nie dostać ani jednej wiadomości więcej.
"""
import json
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from accounts.models import Subscription
from accounts.plans import PLANS, allows_white_label, get_plan
from api.views.stripe_webhook import activate_subscription


def owner_client(user, tenant):
    user.tenant = tenant
    user.role = "owner"
    user.save()
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_API_KEY=str(tenant.api_key))
    return client


class TestKatalogPlanow:
    def test_kazdy_plan_ma_cene_i_limit(self):
        for kod, plan in PLANS.items():
            assert plan.price_pln > 0, kod
            assert plan.message_limit > 0, kod

    def test_limity_rosna_z_cena(self):
        posortowane = sorted(PLANS.values(), key=lambda p: p.price_pln)
        limity = [p.message_limit for p in posortowane]

        assert limity == sorted(limity)

    def test_basic_nie_ma_bialej_etykiety(self):
        assert allows_white_label("basic") is False
        assert allows_white_label("pro") is True
        assert allows_white_label("enterprise") is True

    def test_nieznany_plan_nie_odbiera_uprawnien(self):
        """
        W bazie są subskrypcje sprzed katalogu, z dowolnym tekstem w plan_type
        (np. "Prymium"). Odmowa odebrałaby białą etykietę klientom, którzy
        mają ją dziś ustawioną.
        """
        assert allows_white_label("Prymium") is True
        assert get_plan("Prymium") is None


@pytest.mark.django_db
class TestAktywacjaPoPlatnosci:
    def test_platnosc_podnosi_limit_ktory_egzekwuje_middleware(self, tenant, subscribtion):
        """Sedno naprawy: zapłata musi zmienić Subscription, nie tylko Tenant."""
        activate_subscription(tenant, "enterprise")

        subskrypcja = Subscription.objects.get(tenant=tenant)
        assert subskrypcja.plan_type == "enterprise"
        assert subskrypcja.message_limit == 20_000
        assert subskrypcja.is_active is True

    def test_subskrypcja_powstaje_gdy_jej_nie_bylo(self, tenant):
        """Rejestracja od razu z płatnością — nie ma jeszcze czego aktualizować."""
        assert not Subscription.objects.filter(tenant=tenant).exists()

        activate_subscription(tenant, "basic")

        subskrypcja = Subscription.objects.get(tenant=tenant)
        assert subskrypcja.message_limit == 1_000

    def test_stan_na_tenancie_jest_zsynchronizowany(self, tenant, subscribtion):
        activate_subscription(tenant, "pro")

        tenant.refresh_from_db()
        assert tenant.subscription_status == "active"
        assert tenant.subscription_plan == "pro"

    def test_zmiana_planu_nadpisuje_limit(self, tenant, subscribtion):
        activate_subscription(tenant, "basic")
        activate_subscription(tenant, "enterprise")

        subskrypcja = Subscription.objects.get(tenant=tenant)
        assert subskrypcja.message_limit == 20_000


@pytest.mark.django_db
class TestWebhook:
    URL = "/api/billing/webhook/"

    def _zdarzenie(self, typ, tenant, plan="pro"):
        return {
            "type": typ,
            "data": {"object": {"metadata": {"tenant_id": str(tenant.id), "plan": plan}}},
        }

    def test_webhook_jest_osiagalny_bez_tokenu(self, tenant, subscribtion):
        """
        Stripe woła z własnych serwerów — bez JWT i bez klucza API.
        Wcześniej TenantMiddleware odrzuciłby takie żądanie.
        """
        with patch("stripe.Webhook.construct_event",
                   return_value=self._zdarzenie("checkout.session.completed", tenant)):
            response = APIClient().post(
                self.URL, data=json.dumps({}), content_type="application/json",
                HTTP_STRIPE_SIGNATURE="podpis",
            )

        assert response.status_code == 200
        assert Subscription.objects.get(tenant=tenant).plan_type == "pro"

    def test_bledny_podpis_nic_nie_zmienia(self, tenant, subscribtion):
        """Bez tej weryfikacji każdy mógłby aktywować sobie dowolny plan."""
        import stripe

        with patch("stripe.Webhook.construct_event",
                   side_effect=stripe.error.SignatureVerificationError("zly", "sig")):
            response = APIClient().post(
                self.URL, data=json.dumps({}), content_type="application/json",
                HTTP_STRIPE_SIGNATURE="podrobiony",
            )

        assert response.status_code == 400
        subscribtion.refresh_from_db()
        assert subscribtion.plan_type != "enterprise"

    def test_nieudana_platnosc_wstrzymuje_subskrypcje(self, tenant, subscribtion):
        with patch("stripe.Webhook.construct_event",
                   return_value=self._zdarzenie("invoice.payment_failed", tenant)):
            response = APIClient().post(
                self.URL, data=json.dumps({}), content_type="application/json",
                HTTP_STRIPE_SIGNATURE="podpis",
            )

        assert response.status_code == 200
        subscribtion.refresh_from_db()
        assert subscribtion.is_active is False

    def test_zdarzenie_bez_tenant_id_nie_powtarza_sie_w_nieskonczonosc(self, tenant):
        """Kod błędu kazałby Stripe'owi ponawiać zdarzenie, którego nie da się obsłużyć."""
        with patch("stripe.Webhook.construct_event",
                   return_value={"type": "checkout.session.completed",
                                 "data": {"object": {"metadata": {}}}}):
            response = APIClient().post(
                self.URL, data=json.dumps({}), content_type="application/json",
                HTTP_STRIPE_SIGNATURE="podpis",
            )

        assert response.status_code == 200


@pytest.mark.django_db
class TestBlokadaBialejEtykiety:
    URL = "/api/widget-settings/mine/"

    def test_basic_nie_wlaczy_wlasnego_brandingu(self, user, tenant, subscribtion):
        """Ograniczenie istniało wyłącznie w cenniku — PATCH-em dało się je obejść."""
        subscribtion.plan_type = "basic"
        subscribtion.save()

        response = owner_client(user, tenant).patch(
            self.URL, {"branding_mode": "white_label"}, format="json"
        )

        assert response.status_code == 403
        tenant.refresh_from_db()
        assert tenant.branding_mode != "white_label"

    def test_pro_wlacza_bez_przeszkod(self, user, tenant, subscribtion):
        subscribtion.plan_type = "pro"
        subscribtion.save()

        response = owner_client(user, tenant).patch(
            self.URL, {"branding_mode": "white_label"}, format="json"
        )

        assert response.status_code == 200
        tenant.refresh_from_db()
        assert tenant.branding_mode == "white_label"

    def test_basic_moze_zmieniac_pozostale_ustawienia(self, user, tenant, subscribtion):
        """Blokada dotyczy tylko brandingu — reszta panelu ma działać normalnie."""
        subscribtion.plan_type = "basic"
        subscribtion.save()

        response = owner_client(user, tenant).patch(
            self.URL, {"widget_welcome_message": "Dzień dobry!"}, format="json"
        )

        assert response.status_code == 200
        tenant.refresh_from_db()
        assert tenant.widget_welcome_message == "Dzień dobry!"


@pytest.mark.django_db
class TestCheckout:
    URL = "/api/billing/create-checkout-session/"

    def test_nieznany_plan_jest_odrzucany(self, user, tenant, subscribtion):
        response = owner_client(user, tenant).post(
            self.URL, {"plan_type": "zlotyplan"}, format="json"
        )

        assert response.status_code == 400

    def test_brak_identyfikatora_ceny_daje_czytelny_blad(self, user, tenant, subscribtion, settings):
        """
        Zanim wpiszesz ceny ze Stripe, zakup ma się kończyć zrozumiałym
        komunikatem, a nie pięćsetką z wnętrza biblioteki.
        """
        settings.STRIPE_PRICE_IDS = {"basic": "", "pro": "", "enterprise": ""}

        response = owner_client(user, tenant).post(
            self.URL, {"plan_type": "pro"}, format="json"
        )

        assert response.status_code == 400
        assert "nie jest jeszcze dostępny" in str(response.json())

    def test_sesja_niesie_tenant_id_w_metadanych(self, user, tenant, subscribtion, settings):
        """Bez tego webhook nie ma po czym rozpoznać, kto zapłacił."""
        settings.STRIPE_PRICE_IDS = {"pro": "price_test", "basic": "", "enterprise": ""}

        class FakeSession:
            url = "https://checkout.stripe.test/sesja"

        with patch("stripe.checkout.Session.create", return_value=FakeSession()) as create:
            response = owner_client(user, tenant).post(
                self.URL, {"plan_type": "pro"}, format="json"
            )

        assert response.status_code == 200
        metadane = create.call_args.kwargs["metadata"]
        assert metadane["tenant_id"] == str(tenant.id)
        assert metadane["plan"] == "pro"
        # Odnowienia dotyczą subskrypcji, nie sesji — bez tych metadanych
        # nie dałoby się powiązać kolejnych płatności z firmą
        assert create.call_args.kwargs["subscription_data"]["metadata"]["tenant_id"] == str(tenant.id)
