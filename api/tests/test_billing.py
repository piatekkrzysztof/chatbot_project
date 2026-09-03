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
from accounts.plans import (
    PLANS,
    allows_hiding_branding,
    allows_white_label,
    get_plan,
)
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

    def test_branding_rosnie_wraz_z_planem(self):
        """
        Badanie rozdziela trzy progi, nie dwa: START reklamuje nas w stopce,
        GROW pozwala ją ukryć, dopiero PRO daje własną markę.
        """
        assert allows_white_label("start") is False
        assert allows_white_label("grow") is False
        assert allows_white_label("pro") is True

        assert allows_hiding_branding("start") is False
        assert allows_hiding_branding("grow") is True
        assert allows_hiding_branding("pro") is True

    @pytest.mark.parametrize(
        "kod,cena,cena_roczna,wiadomosci,baza_mb,boty,miejsca",
        [
            ("start", 149, 119, 2_000, 5, 1, 1),
            ("grow", 349, 279, 8_000, 25, 3, 3),
            ("pro", 899, 719, 25_000, 100, 10, 10),
        ],
    )
    def test_cennik_zgodny_z_badaniem(
        self, kod, cena, cena_roczna, wiadomosci, baza_mb, boty, miejsca
    ):
        """
        Liczby pochodzą z badania rynku (sierpień 2026) i są argumentem
        sprzedażowym, nie dowolnym ustawieniem: ChatBotXL bierze 149 zł za
        500 wiadomości, więc nasz START za tę samą cenę daje ich cztery razy
        więcej. Cicha zmiana którejkolwiek z nich psuje pozycjonowanie.
        """
        plan = PLANS[kod]

        assert plan.price_pln == cena
        assert plan.price_pln_yearly == cena_roczna
        assert plan.message_limit == wiadomosci
        assert plan.knowledge_base_mb == baza_mb
        # max_bots celowo nie ma w katalogu: cennik obiecywał 1/3/10 botów,
        # a modelu wielu botów nigdy nie zbudowano. Wróci razem z funkcją.
        assert plan.max_domains == boty
        assert plan.max_seats == miejsca

    def test_cena_roczna_to_rabat_okolo_dwudziestu_procent(self):
        for plan in PLANS.values():
            rabat = 1 - plan.price_pln_yearly / plan.price_pln

            assert 0.18 <= rabat <= 0.22, f"{plan.code}: rabat {rabat:.0%}"

    def test_limity_rosna_wraz_z_cena(self):
        """Wyższy plan musi dawać więcej pod każdym względem — inaczej cennik kłamie."""
        kolejne = [PLANS["start"], PLANS["grow"], PLANS["pro"]]

        for nizszy, wyzszy in zip(kolejne, kolejne[1:]):
            assert wyzszy.price_pln > nizszy.price_pln
            assert wyzszy.message_limit > nizszy.message_limit
            assert wyzszy.knowledge_base_mb > nizszy.knowledge_base_mb
            assert wyzszy.max_seats > nizszy.max_seats
            assert wyzszy.rate_per_minute > nizszy.rate_per_minute

    def test_stare_kody_planow_nadal_dzialaja(self):
        """
        Subskrypcje kupione przed zmianą cennika trzymają w bazie stary kod.
        Bez mapowania trafiłyby w gałąź "plan nierozpoznany" i dostały
        zaniżone limity, choć klient zapłacił.
        """
        assert get_plan("basic").code == "start"
        assert get_plan("enterprise").code == "pro"

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
        activate_subscription(tenant, "pro")

        subskrypcja = Subscription.objects.get(tenant=tenant)
        assert subskrypcja.plan_type == "pro"
        assert subskrypcja.message_limit == 25_000
        assert subskrypcja.is_active is True

    def test_subskrypcja_powstaje_gdy_jej_nie_bylo(self, tenant):
        """Rejestracja od razu z płatnością — nie ma jeszcze czego aktualizować."""
        assert not Subscription.objects.filter(tenant=tenant).exists()

        activate_subscription(tenant, "start")

        subskrypcja = Subscription.objects.get(tenant=tenant)
        assert subskrypcja.message_limit == 2_000

    def test_stan_na_tenancie_jest_zsynchronizowany(self, tenant, subscribtion):
        activate_subscription(tenant, "pro")

        tenant.refresh_from_db()
        assert tenant.subscription_status == "active"
        assert tenant.subscription_plan == "pro"

    def test_zmiana_planu_nadpisuje_limit(self, tenant, subscribtion):
        activate_subscription(tenant, "start")
        activate_subscription(tenant, "pro")

        subskrypcja = Subscription.objects.get(tenant=tenant)
        assert subskrypcja.message_limit == 25_000


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
        with patch(
            "stripe.Webhook.construct_event",
            return_value=self._zdarzenie("checkout.session.completed", tenant),
        ):
            response = APIClient().post(
                self.URL,
                data=json.dumps({}),
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="podpis",
            )

        assert response.status_code == 200
        assert Subscription.objects.get(tenant=tenant).plan_type == "pro"

    def test_bledny_podpis_nic_nie_zmienia(self, tenant, subscribtion):
        """Bez tej weryfikacji każdy mógłby aktywować sobie dowolny plan."""
        import stripe

        with patch(
            "stripe.Webhook.construct_event",
            side_effect=stripe.error.SignatureVerificationError("zly", "sig"),
        ):
            response = APIClient().post(
                self.URL,
                data=json.dumps({}),
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="podrobiony",
            )

        assert response.status_code == 400
        subscribtion.refresh_from_db()
        assert subscribtion.plan_type != "pro"

    def test_nieudana_platnosc_wstrzymuje_subskrypcje(self, tenant, subscribtion):
        with patch(
            "stripe.Webhook.construct_event",
            return_value=self._zdarzenie("invoice.payment_failed", tenant),
        ):
            response = APIClient().post(
                self.URL,
                data=json.dumps({}),
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="podpis",
            )

        assert response.status_code == 200
        subscribtion.refresh_from_db()
        assert subscribtion.is_active is False

    def test_zdarzenie_bez_tenant_id_nie_powtarza_sie_w_nieskonczonosc(self, tenant):
        """Kod błędu kazałby Stripe'owi ponawiać zdarzenie, którego nie da się obsłużyć."""
        with patch(
            "stripe.Webhook.construct_event",
            return_value={
                "type": "checkout.session.completed",
                "data": {"object": {"metadata": {}}},
            },
        ):
            response = APIClient().post(
                self.URL,
                data=json.dumps({}),
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="podpis",
            )

        assert response.status_code == 200


@pytest.mark.django_db
class TestBlokadaBialejEtykiety:
    URL = "/api/widget-settings/mine/"

    def test_start_nie_wlaczy_wlasnego_brandingu(self, user, tenant, subscribtion):
        """Ograniczenie istniało wyłącznie w cenniku — PATCH-em dało się je obejść."""
        subscribtion.plan_type = "start"
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

    def test_start_moze_zmieniac_pozostale_ustawienia(self, user, tenant, subscribtion):
        """Blokada dotyczy tylko brandingu — reszta panelu ma działać normalnie."""
        subscribtion.plan_type = "start"
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

    def test_brak_identyfikatora_ceny_daje_czytelny_blad(
        self, user, tenant, subscribtion, settings
    ):
        """
        Zanim wpiszesz ceny ze Stripe, zakup ma się kończyć zrozumiałym
        komunikatem, a nie pięćsetką z wnętrza biblioteki.
        """
        settings.STRIPE_PRICE_IDS = {"start": "", "grow": "", "pro": ""}

        response = owner_client(user, tenant).post(self.URL, {"plan_type": "pro"}, format="json")

        assert response.status_code == 400
        assert "nie jest jeszcze dostępny" in str(response.json())

    def test_sesja_niesie_tenant_id_w_metadanych(self, user, tenant, subscribtion, settings):
        """Bez tego webhook nie ma po czym rozpoznać, kto zapłacił."""
        settings.STRIPE_PRICE_IDS = {"pro": "price_test", "start": "", "grow": ""}

        class FakeSession:
            url = "https://checkout.stripe.test/sesja"

        # Kartoteka klienta jest osobna sprawa (test_stripe_klient.py). Bez
        # tego podstawienia wywolanie wychodzi na zewnatrz, konczy sie bledem,
        # kod wpada w droge awaryjna - a test przechodzi, sprawdzajac nie te
        # sciezke, o ktora pyta.
        with (
            patch("api.views.stripe.kartoteka_klienta", return_value="cus_test"),
            patch("stripe.checkout.Session.create", return_value=FakeSession()) as create,
        ):
            response = owner_client(user, tenant).post(
                self.URL, {"plan_type": "pro"}, format="json"
            )

        assert response.status_code == 200
        metadane = create.call_args.kwargs["metadata"]
        assert metadane["tenant_id"] == str(tenant.id)
        assert metadane["plan"] == "pro"
        # Odnowienia dotyczą subskrypcji, nie sesji — bez tych metadanych
        # nie dałoby się powiązać kolejnych płatności z firmą
        assert create.call_args.kwargs["subscription_data"]["metadata"]["tenant_id"] == str(
            tenant.id
        )


@pytest.mark.django_db
class TestCennikWPanelu:
    URL = "/api/billing/plans/"

    def test_panel_dostaje_ceny_z_backendu(self, user, tenant, subscribtion):
        """
        Panel nie ma własnej kopii cennika — inaczej rozjechałby się z tym,
        co naprawdę obowiązuje przy zakupie.
        """
        dane = owner_client(user, tenant).get(self.URL).json()

        kody = {p["code"] for p in dane["plans"]}
        assert kody == set(PLANS)
        start = next(p for p in dane["plans"] if p["code"] == "start")
        assert start["price_pln"] == 149
        assert start["price_pln_yearly"] == 119
        assert start["message_limit"] == 2_000
        assert start["white_label"] is False

    def test_plan_bez_ceny_w_stripe_jest_oznaczony_jako_niedostepny(
        self, user, tenant, subscribtion, settings
    ):
        """Zanim wpiszesz ceny, panel ma to pokazać zamiast prowadzić w ślepy zaułek."""
        settings.STRIPE_PRICE_IDS = {"start": "price_x", "grow": "", "pro": ""}

        dane = owner_client(user, tenant).get(self.URL).json()

        dostepnosc = {p["code"]: p["available"] for p in dane["plans"]}
        assert dostepnosc == {"start": True, "grow": False, "pro": False}

    def test_biezacy_plan_i_zuzycie(self, user, tenant, subscribtion):
        subscribtion.plan_type = "pro"
        subscribtion.message_limit = 5_000
        subscribtion.current_message_count = 120
        subscribtion.save()

        biezacy = owner_client(user, tenant).get(self.URL).json()["current"]

        assert biezacy["plan"] == "pro"
        assert biezacy["in_catalogue"] is True
        assert biezacy["used"] == 120
        assert biezacy["limit"] == 5_000

    def test_plan_spoza_cennika_nie_znika_z_widoku(self, user, tenant, subscribtion):
        """Na produkcji jest subskrypcja "Prymium" — klient ma zobaczyć swój plan."""
        subscribtion.plan_type = "Prymium"
        subscribtion.save()

        biezacy = owner_client(user, tenant).get(self.URL).json()["current"]

        assert biezacy["name"] == "Prymium"
        assert biezacy["in_catalogue"] is False

    def test_cennik_wymaga_zalogowania(self, tenant):
        assert APIClient().get(self.URL).status_code in (401, 403)


@pytest.mark.django_db
def test_adresy_powrotu_maja_odpowiedniki_w_panelu(user, tenant, subscribtion, settings):
    """
    Stripe odsyła klienta pod adresy podane w sesji. Literówka albo brak strony
    kończy się czterysta czwórką tuż po zapłaceniu — najgorszy możliwy moment.
    Trasy w panelu: app/(admin)/platnosc/sukces i .../anulowano.
    """
    settings.STRIPE_PRICE_IDS = {"pro": "price_test", "start": "", "grow": ""}

    class FakeSession:
        url = "https://checkout.stripe.test/s"

    with (
        patch("api.views.stripe.kartoteka_klienta", return_value="cus_test"),
        patch("stripe.checkout.Session.create", return_value=FakeSession()) as create,
    ):
        owner_client(user, tenant).post(
            "/api/billing/create-checkout-session/", {"plan_type": "pro"}, format="json"
        )

    kwargs = create.call_args.kwargs
    assert "/platnosc/sukces" in kwargs["success_url"]
    assert "/platnosc/anulowano" in kwargs["cancel_url"]


@pytest.mark.django_db
class TestPublicznegoCennika:
    """
    Cennik dla strony sprzedażowej. Czyta go ktoś, kto nie ma jeszcze konta,
    więc nie ma ani tenanta, ani klucza API — a TenantMiddleware domyślnie
    odrzuca wszystko pod /api/. To ten sam wzorzec, który wcześniej blokował
    zaproszenia i webhook Stripe'a.
    """

    URL = "/api/billing/cennik/"

    def test_dziala_bez_logowania(self):
        response = APIClient().get(self.URL)

        assert response.status_code == 200

    def test_zawiera_wszystkie_plany_z_katalogu(self):
        dane = APIClient().get(self.URL).json()

        assert [p["code"] for p in dane["plans"]] == list(PLANS)

    def test_ceny_zgadzaja_sie_z_katalogiem(self):
        """
        Strona sprzedażowa nie może mieć własnej kopii cen — rozjechałaby się
        z tym, co klient realnie zapłaci przy zakupie.
        """
        dane = APIClient().get(self.URL).json()

        for pozycja in dane["plans"]:
            plan = PLANS[pozycja["code"]]
            assert pozycja["price_pln"] == plan.price_pln
            assert pozycja["price_pln_yearly"] == plan.price_pln_yearly
            assert pozycja["message_limit"] == plan.message_limit

    def test_nie_zdradza_niczego_o_firmach(self):
        """Endpoint jest publiczny — nie może wyciekać stanem subskrypcji."""
        dane = APIClient().get(self.URL).json()

        assert "current" not in dane
        assert all("available" not in p for p in dane["plans"])

    def test_zawiera_pakiet_dodatkowy(self):
        dane = APIClient().get(self.URL).json()

        assert dane["pakiet"] == {"wiadomosci": 1000, "cena_pln": 39}


@pytest.mark.django_db
class TestRejestracjiZOkresemProbnym:
    """
    Rejestracja bez karty musi dać działającego bota.

    SubscriptionMiddleware wymaga rekordu subskrypcji dla /api/widget/chat/,
    a rejestracja próbna go nie tworzyła — klient konfigurowałby wszystko,
    wkleił kod na stronę i zobaczył odmowę zamiast odpowiedzi.
    """

    URL = "/api/accounts/register/"

    def zarejestruj(self, email="nowy@example.com"):
        return APIClient().post(
            self.URL,
            {
                "imie": "Anna",
                "nazwisko": "Nowak",
                "company_name": "Nowa Firma",
                "email": email,
                "password": "tajneHaslo123",
                # Dane do faktury zbierane juz przy rejestracji - klient
                # dochodzacy do platnosci nie dostaje drugiego formularza.
                "ulica": "Krakowska 12",
                "kod_pocztowy": "31-000",
                "miasto": "Krakow",
                "use_trial": True,
            },
            format="json",
        )

    def test_konto_powstaje(self):
        from accounts.models import Tenant

        response = self.zarejestruj()

        assert response.status_code == 201
        assert Tenant.objects.filter(name="Nowa Firma").exists()

    def test_powstaje_subskrypcja_probna(self):
        from accounts.models import Subscription, Tenant

        self.zarejestruj()
        tenant = Tenant.objects.get(name="Nowa Firma")

        subskrypcja = Subscription.objects.get(tenant=tenant)
        assert subskrypcja.is_active
        assert subskrypcja.plan_type == "start"
        assert subskrypcja.message_limit == PLANS["start"].message_limit

    def test_okres_probny_ma_date_konca(self):
        from datetime import date, timedelta

        from accounts.models import Subscription, Tenant

        self.zarejestruj()
        subskrypcja = Subscription.objects.get(tenant__name="Nowa Firma")

        assert subskrypcja.end_date == date.today() + timedelta(days=14)

    def test_widget_odpowiada_zaraz_po_rejestracji(self, mocker):
        """
        Sedno poprawki: sprawdzamy nie stan bazy, tylko to, czy bot faktycznie
        odpowiada. Wcześniej ten sam scenariusz kończył się odmową 403.
        """
        import uuid

        from accounts.models import Tenant

        mocker.patch(
            "api.utils.chat_engine.get_openai_response",
            return_value={"content": "Dzień dobry!", "tokens": 5},
        )
        self.zarejestruj()
        tenant = Tenant.objects.get(name="Nowa Firma")

        response = APIClient().post(
            "/api/widget/chat/",
            {"message": "Dzień dobry", "conversation_session_id": str(uuid.uuid4())},
            format="json",
            HTTP_X_API_KEY=str(tenant.api_key),
        )

        assert response.status_code == 200, response.data
