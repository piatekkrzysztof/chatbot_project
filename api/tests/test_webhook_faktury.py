"""
Rozpoznawanie firmy przy zdarzeniach fakturowych ze Stripe.

Webhook szukal tenant_id w `event["data"]["object"]["metadata"]`. Dla sesji
platnosci i dla subskrypcji to dziala, bo metadane ustawiamy wlasnie tam.
Dla faktury nie: faktura ma WLASNE pole `metadata`, niezalezne od metadanych
subskrypcji, a my nigdy go nie wypelniamy.

Skutek byl cichy i kosztowny. Oba zdarzenia `invoice.*` konczyly sie na
galezi "bez tenant_id — pomijam" ze statusem 200, wiec w panelu Stripe
widnialo zielone "delivered":

  * odnowienie miesieczne nie przedluzalo subskrypcji — klient placil,
    a jego konto wygasalo po pierwszym okresie,
  * nieudana platnosc nie zawieszala konta — klient przestawal placic
    i korzystal dalej.

Adres subskrypcji na fakturze przesuwal sie miedzy wersjami API Stripe,
dlatego testy sprawdzaja kilka ksztaltow naraz.
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from accounts.models import Subscription, Tenant
from api.views.stripe_webhook import identyfikator_subskrypcji


@pytest.fixture
def firma(db):
    tenant = Tenant.objects.create(name="Dwor Weselny", owner_email="w@firma.pl")
    Subscription.objects.create(
        tenant=tenant,
        plan_type="start",
        is_active=True,
        message_limit=2000,
        current_message_count=0,
        start_date=date.today() - timedelta(days=40),
        end_date=date.today() - timedelta(days=9),
    )
    return tenant


class TestZnajdowaniaSubskrypcji:
    """
    Od F11 webhook nie czyta metadanych ze zdarzenia, tylko ustala, której
    subskrypcji dotyczy, i pobiera jej bieżący stan ze Stripe. Te same kształty
    faktury co wcześniej - zmienia się to, co z nich wyciągamy.
    """

    def test_sesja_platnosci_ma_identyfikator_wprost(self):
        assert (
            identyfikator_subskrypcji("checkout.session.completed", {"subscription": "sub_7"})
            == "sub_7"
        )

    def test_zdarzenie_subskrypcji_to_ona_sama(self):
        assert (
            identyfikator_subskrypcji("customer.subscription.deleted", {"id": "sub_7"}) == "sub_7"
        )

    def test_faktura_w_nowszym_ksztalcie(self):
        faktura = {"metadata": {}, "parent": {"subscription_details": {"subscription": "sub_123"}}}

        assert identyfikator_subskrypcji("invoice.payment_succeeded", faktura) == "sub_123"

    def test_faktura_ze_starszym_polem_subscription(self):
        faktura = {"metadata": {}, "subscription": "sub_123"}

        assert identyfikator_subskrypcji("invoice.payment_failed", faktura) == "sub_123"

    def test_faktura_z_rozwinieta_subskrypcja(self):
        """Przy expand=subscription Stripe wstawia caly obiekt zamiast id."""
        faktura = {"metadata": {}, "subscription": {"id": "sub_123", "metadata": {}}}

        assert identyfikator_subskrypcji("invoice.payment_succeeded", faktura) == "sub_123"

    def test_faktura_bez_subskrypcji_daje_pusty_wynik(self):
        """Faktura jednorazowa, nie zwiazana z abonamentem."""
        assert identyfikator_subskrypcji("invoice.payment_succeeded", {"metadata": {}}) == ""

    def test_zdarzenie_niezwiazane_z_subskrypcja(self):
        assert identyfikator_subskrypcji("customer.updated", {"id": "cus_1"}) == ""


@pytest.mark.django_db
class TestPelnejSciezki:
    def _wyslij(self, event_type, data, subskrypcja=None):
        from api.views.stripe_webhook import stripe_webhook

        zdarzenie = {"type": event_type, "data": {"object": data}}
        with (
            patch(
                "api.views.stripe_webhook.stripe.Webhook.construct_event", return_value=zdarzenie
            ),
            patch(
                "api.views.stripe_webhook.stripe.Subscription.retrieve", return_value=subskrypcja
            ),
        ):
            zadanie = MagicMock()
            zadanie.body = b"{}"
            zadanie.META = {"HTTP_STRIPE_SIGNATURE": "podpis"}
            return stripe_webhook(zadanie)

    def _subskrypcja(self, firma, status="active", plan="grow", poczatek_dni=-1):
        import time

        teraz = int(time.time())
        return {
            "id": "sub_123",
            "status": status,
            "current_period_start": teraz + poczatek_dni * 86_400,
            "current_period_end": teraz + 30 * 86_400,
            "metadata": {"tenant_id": str(firma.id), "plan": plan},
            "items": {"data": []},
        }

    def _faktura(self):
        return {"metadata": {}, "parent": {"subscription_details": {"subscription": "sub_123"}}}

    def test_odnowienie_przedluza_subskrypcje(self, firma):
        """
        Sedno naprawy. Subskrypcja wygasla dziewiec dni temu; oplacona faktura
        ma ja przedluzyc, a wczesniej zdarzenie bylo po cichu pomijane.
        """
        odp = self._wyslij("invoice.payment_succeeded", self._faktura(), self._subskrypcja(firma))

        assert odp.status_code == 200
        subskrypcja = Subscription.objects.get(tenant=firma)
        assert subskrypcja.is_active is True
        assert subskrypcja.plan_type == "grow"
        assert subskrypcja.end_date > date.today()

    def test_nieudane_odnowienie_zostawia_oplacony_okres(self, firma):
        """
        Od F11 pierwsza nieudana próba nie odcina czatu: klient korzysta do
        końca opłaconego okresu plus trzy dni na ponowienia Stripe.
        """
        odp = self._wyslij(
            "invoice.payment_failed",
            self._faktura(),
            self._subskrypcja(firma, status="past_due", plan="start"),
        )

        assert odp.status_code == 200
        subskrypcja = Subscription.objects.get(tenant=firma)
        assert subskrypcja.is_active is True
        assert subskrypcja.end_date == date.today() - timedelta(days=1) + timedelta(days=3)
        firma.refresh_from_db()
        assert firma.subscription_status == "past_due"

    def test_zdarzenie_bez_subskrypcji_konczy_sie_200(self, db):
        """Kod bledu kazalby Stripe'owi ponawiac je w nieskonczonosc."""
        odp = self._wyslij("invoice.payment_succeeded", {"metadata": {}})

        assert odp.status_code == 200


@pytest.mark.django_db
class TestBleduStripePrzyZakupie:
    """
    Wyszlo przy konfiguracji trybu testowego: w .env byl klucz testowy,
    a identyfikatory cen produkcyjne. Stripe odpowiadal wprost

        No such price: 'price_...'; a similar object exists in live mode,
        but a test mode key was used

    ale wyjatek nie byl lapany, wiec konczylo sie 500 z pustym komunikatem.
    W panelu wygladalo to tak, ze klikniecie "wybierz plan" nie robi nic.
    Prawdziwy powod szedl wylacznie do logu.
    """

    def _wlasciciel(self, firma):
        from accounts.models import CustomUser

        return CustomUser.objects.create_user(
            username="wl",
            email="wl@firma.pl",
            password="x",
            tenant=firma,
            role="owner",
        )

    def test_odmowa_stripe_konczy_sie_czytelnym_bledem(self, firma, settings):
        import stripe as biblioteka
        from rest_framework.exceptions import ValidationError

        from api.views.stripe import create_checkout_session

        settings.STRIPE_PRICE_IDS = {"start": "price_z_produkcji", "grow": "", "pro": ""}
        settings.STRIPE_SECRET_KEY = "sk_test_cokolwiek"

        with patch(
            "api.views.stripe._utworz_sesje",
            side_effect=biblioteka.error.InvalidRequestError(
                "No such price: 'price_z_produkcji'", param="price"
            ),
        ):
            with pytest.raises(ValidationError) as blad:
                create_checkout_session(firma, "start", "klient@firma.pl")

        assert "Nie udało się rozpocząć płatności" in str(blad.value)

    def test_panel_dostaje_400_a_nie_500(self, firma, settings):
        """Kod 500 z pusta trescia panel pokazuje jako nic — a klient siedzi
        i klika dalej, przekonany, ze przycisk jest zepsuty."""
        import stripe as biblioteka
        from rest_framework.test import APIClient

        settings.STRIPE_PRICE_IDS = {"start": "price_z_produkcji", "grow": "", "pro": ""}
        settings.STRIPE_SECRET_KEY = "sk_test_cokolwiek"

        klient = APIClient()
        klient.force_authenticate(user=self._wlasciciel(firma))
        klient.credentials(HTTP_X_API_KEY=str(firma.api_key))

        with patch(
            "api.views.stripe._utworz_sesje",
            side_effect=biblioteka.error.APIConnectionError("brak sieci"),
        ):
            odp = klient.post(
                "/api/billing/create-checkout-session/", {"plan_type": "start"}, format="json"
            )

        assert odp.status_code == 400
        assert "płatności" in str(odp.data)

    def test_brak_ceny_dalej_mowi_wprost_ktory_plan(self, firma, settings):
        """Ten komunikat istnial wczesniej i ma zostac — dotyczy innej
        sytuacji: ceny w ogole nie skonfigurowano."""
        from rest_framework.exceptions import ValidationError

        from api.views.stripe import create_checkout_session

        settings.STRIPE_PRICE_IDS = {"start": "", "grow": "", "pro": ""}

        with pytest.raises(ValidationError) as blad:
            create_checkout_session(firma, "start", "klient@firma.pl")

        assert "nie jest jeszcze dostępny" in str(blad.value)


@pytest.mark.django_db
class TestDostepnosciEndpointu:
    """
    Regresja, ktora sam wprowadzilem: wstawiajac funkcje pomocnicze miedzy
    dekorator @csrf_exempt a widok, przeniosłem dekorator na funkcje
    pomocnicza. Webhook stracil zwolnienie z CSRF i odpowiadal 403 na KAZDE
    zdarzenie ze Stripe -- zanim jakikolwiek kod webhooka sie wykonal.

    Objaw byl mylacy: platnosc w Stripe konczyla sie sukcesem, a w bazie
    nie dzialo sie nic. Zaden log aplikacji tego nie pokazywal, bo zadanie
    nie doszlo do widoku.
    """

    def test_post_bez_tokenu_csrf_nie_jest_odrzucany(self):
        """
        Stripe wysyla POST bez ciasteczka sesji i bez tokenu CSRF. Bez
        zwolnienia Django odrzuca go kodem 403.

        enforce_csrf_checks=True jest tu konieczne: zwykly klient testowy
        Django omija ochrone CSRF, wiec bez tego test przechodzilby takze
        z zepsutym dekoratorem.
        """
        from django.test import Client

        klient = Client(enforce_csrf_checks=True)
        odp = klient.post(
            "/api/billing/webhook/",
            data="{}",
            content_type="application/json",
        )

        assert odp.status_code != 403, "webhook stracil zwolnienie z CSRF"
        # 400 = doszlo do widoku i odrzucilo brak podpisu, czyli dokladnie to,
        # czego oczekujemy od zadania bez naglowka Stripe-Signature
        assert odp.status_code == 400

    def test_widok_ma_dekorator_bezposrednio(self):
        """Pilnuje samego ustawienia, a nie tylko skutku — gdyby ktos znowu
        wstawil cos miedzy dekorator a widok."""
        from api.views.stripe_webhook import stripe_webhook

        assert getattr(stripe_webhook, "csrf_exempt", False) is True
