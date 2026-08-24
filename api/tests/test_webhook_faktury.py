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
from api.views.stripe_webhook import _metadane_zdarzenia


@pytest.fixture
def firma(db):
    tenant = Tenant.objects.create(name="Dwor Weselny", owner_email="w@firma.pl")
    Subscription.objects.create(
        tenant=tenant, plan_type="start", is_active=True, message_limit=2000,
        current_message_count=0, start_date=date.today() - timedelta(days=40),
        end_date=date.today() - timedelta(days=9),
    )
    return tenant


class TestZnajdowaniaFirmy:
    def test_sesja_platnosci_ma_metadane_wprost(self):
        """Tu zawsze dzialalo — pilnujemy, zeby naprawa tego nie zepsula."""
        sesja = {"metadata": {"tenant_id": "7", "plan": "grow"}}

        assert _metadane_zdarzenia("checkout.session.completed", sesja)["tenant_id"] == "7"

    def test_subskrypcja_ma_metadane_wprost(self):
        subskrypcja = {"metadata": {"tenant_id": "7", "plan": "grow"}}

        assert _metadane_zdarzenia("customer.subscription.deleted", subskrypcja)["tenant_id"] == "7"

    def test_faktura_w_nowszym_ksztalcie_nie_wymaga_pytania_stripe(self):
        """
        Nowsze wersje API niosa metadane subskrypcji wprost w fakturze.
        Dodatkowe wywolanie API byloby wtedy strata czasu i limitu.
        """
        faktura = {
            "metadata": {},
            "parent": {"subscription_details": {
                "subscription": "sub_123",
                "metadata": {"tenant_id": "7", "plan": "grow"},
            }},
        }

        with patch("api.views.stripe_webhook.stripe.Subscription.retrieve") as pytanie:
            wynik = _metadane_zdarzenia("invoice.payment_succeeded", faktura)

        assert wynik["tenant_id"] == "7"
        assert not pytanie.called

    def test_faktura_ze_starszym_polem_subscription(self):
        """Klasyczny ksztalt: sam identyfikator subskrypcji, metadane trzeba
        pobrac ze Stripe."""
        faktura = {"metadata": {}, "subscription": "sub_123"}

        with patch("api.views.stripe_webhook.stripe.Subscription.retrieve") as pytanie:
            pytanie.return_value = {"metadata": {"tenant_id": "7", "plan": "pro"}}
            wynik = _metadane_zdarzenia("invoice.payment_failed", faktura)

        assert wynik["tenant_id"] == "7"
        pytanie.assert_called_once_with("sub_123")

    def test_faktura_z_rozwinieta_subskrypcja(self):
        """Przy expand=subscription Stripe wstawia caly obiekt zamiast id."""
        faktura = {
            "metadata": {},
            "subscription": {"id": "sub_123", "metadata": {"tenant_id": "7"}},
        }

        with patch("api.views.stripe_webhook.stripe.Subscription.retrieve") as pytanie:
            wynik = _metadane_zdarzenia("invoice.payment_succeeded", faktura)

        assert wynik["tenant_id"] == "7"
        assert not pytanie.called

    def test_wlasne_metadane_faktury_maja_pierwszenstwo(self):
        """Gdyby kiedys ustawic je wprost na fakturze, nie ma sensu pytac dalej."""
        faktura = {"metadata": {"tenant_id": "9"}, "subscription": "sub_123"}

        with patch("api.views.stripe_webhook.stripe.Subscription.retrieve") as pytanie:
            wynik = _metadane_zdarzenia("invoice.payment_succeeded", faktura)

        assert wynik["tenant_id"] == "9"
        assert not pytanie.called

    def test_awaria_zapytania_do_stripe_nie_wywraca_webhooka(self):
        """Webhook ma oddac 200, a nie 500 — inaczej Stripe ponawia zdarzenie
        w nieskonczonosc, a przyczyna i tak lezy gdzie indziej."""
        faktura = {"metadata": {}, "subscription": "sub_123"}

        with patch("api.views.stripe_webhook.stripe.Subscription.retrieve",
                   side_effect=Exception("Stripe nie odpowiada")):
            assert _metadane_zdarzenia("invoice.payment_succeeded", faktura) == {}

    def test_faktura_bez_subskrypcji_daje_pusty_wynik(self):
        """Faktura jednorazowa, nie zwiazana z abonamentem."""
        assert _metadane_zdarzenia("invoice.payment_succeeded", {"metadata": {}}) == {}


@pytest.mark.django_db
class TestPelnejSciezki:
    def _wyslij(self, klient, event_type, data):
        from api.views.stripe_webhook import stripe_webhook

        zdarzenie = {"type": event_type, "data": {"object": data}}
        with patch("api.views.stripe_webhook.stripe.Webhook.construct_event",
                   return_value=zdarzenie):
            zadanie = MagicMock()
            zadanie.body = b"{}"
            zadanie.META = {"HTTP_STRIPE_SIGNATURE": "podpis"}
            return stripe_webhook(zadanie)

    def test_odnowienie_przedluza_subskrypcje(self, firma):
        """
        Sedno naprawy. Subskrypcja wygasla dziewiec dni temu; oplacona faktura
        ma ja przedluzyc, a wczesniej zdarzenie bylo po cichu pomijane.
        """
        faktura = {
            "metadata": {},
            "parent": {"subscription_details": {
                "metadata": {"tenant_id": str(firma.id), "plan": "grow"},
            }},
        }

        odp = self._wyslij(None, "invoice.payment_succeeded", faktura)

        assert odp.status_code == 200
        subskrypcja = Subscription.objects.get(tenant=firma)
        assert subskrypcja.is_active is True
        assert subskrypcja.plan_type == "grow"
        assert subskrypcja.end_date > date.today()

    def test_nieudana_platnosc_zawiesza_konto(self, firma):
        faktura = {
            "metadata": {},
            "parent": {"subscription_details": {
                "metadata": {"tenant_id": str(firma.id), "plan": "start"},
            }},
        }

        odp = self._wyslij(None, "invoice.payment_failed", faktura)

        assert odp.status_code == 200
        assert Subscription.objects.get(tenant=firma).is_active is False
        firma.refresh_from_db()
        assert firma.subscription_status == "suspended"

    def test_zdarzenie_bez_firmy_konczy_sie_200(self, db):
        """Kod bledu kazalby Stripe'owi ponawiac je w nieskonczonosc."""
        odp = self._wyslij(None, "invoice.payment_succeeded", {"metadata": {}})

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
            username="wl", email="wl@firma.pl", password="x",
            tenant=firma, role="owner",
        )

    def test_odmowa_stripe_konczy_sie_czytelnym_bledem(self, firma, settings):
        import stripe as biblioteka
        from rest_framework.exceptions import ValidationError

        from api.views.stripe import create_checkout_session

        settings.STRIPE_PRICE_IDS = {"start": "price_z_produkcji", "grow": "", "pro": ""}
        settings.STRIPE_SECRET_KEY = "sk_test_cokolwiek"

        with patch("api.views.stripe._utworz_sesje",
                   side_effect=biblioteka.error.InvalidRequestError(
                       "No such price: 'price_z_produkcji'", param="price")):
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

        with patch("api.views.stripe._utworz_sesje",
                   side_effect=biblioteka.error.APIConnectionError("brak sieci")):
            odp = klient.post("/api/billing/create-checkout-session/",
                              {"plan_type": "start"}, format="json")

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
            data="{}", content_type="application/json",
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
