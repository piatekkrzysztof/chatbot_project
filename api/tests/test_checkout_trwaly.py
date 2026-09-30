"""Jedna możliwa do opłacenia sesja, również po awarii i zmianie planu."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Event
from unittest.mock import patch

import pytest
import stripe
from django.db import DatabaseError, close_old_connections, connections, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.checkout import ProbaZakupu
from accounts.models import Tenant
from api.utils.checkout import CheckoutDoWyjasnienia, CheckoutZajety, CheckoutZakonczony
from api.views.stripe import create_checkout_session


class StripeAtrapa:
    """Stan usługi przeżywa rollback lokalnej bazy, tak jak prawdziwy Stripe."""

    def __init__(self):
        self.sesje, self.klucze = {}, {}
        self.odpowiedzi = {}
        self.utworzenia, self.wygaszenia = [], []
        self.zgub_odpowiedz = False

    def create(self, **parametry):
        self.utworzenia.append(deepcopy(parametry))
        klucz = parametry.pop("idempotency_key")
        if klucz in self.klucze:
            sid, poprzednie = self.klucze[klucz]
            assert parametry == poprzednie, "Zmiana parametrów przy tym samym kluczu"
        else:
            sid = f"cs_test_audit{len(self.sesje):08}"
            self.sesje[sid] = {
                "id": sid,
                "status": "open",
                "url": f"https://checkout.stripe.test/{sid}",
                "subscription": None,
                **deepcopy(parametry),
            }
            self.klucze[klucz] = (sid, deepcopy(parametry))
            self.odpowiedzi[klucz] = deepcopy(self.sesje[sid])
        if self.zgub_odpowiedz:
            self.zgub_odpowiedz = False
            raise stripe.APIConnectionError("Utworzono, ale odpowiedź nie dotarła")
        return deepcopy(self.odpowiedzi[klucz])

    def retrieve(self, sid):
        return deepcopy(self.sesje[sid])

    def expire(self, sid):
        if self.sesje[sid]["status"] != "open":
            raise stripe.InvalidRequestError("Session is not open", param="id")
        self.sesje[sid]["status"] = "expired"
        self.wygaszenia.append(sid)
        return self.retrieve(sid)


@pytest.fixture
def provider(settings):
    settings.STRIPE_PRICE_IDS = {"pro": "price_pro", "grow": "price_grow"}
    atrapa = StripeAtrapa()
    with (
        patch("api.views.stripe.kartoteka_klienta", return_value="cus_test"),
        patch("stripe.checkout.Session.create", side_effect=atrapa.create),
        patch("stripe.checkout.Session.retrieve", side_effect=atrapa.retrieve),
        patch("stripe.checkout.Session.expire", side_effect=atrapa.expire),
    ):
        yield atrapa


@pytest.mark.django_db
def test_granica_okna_nie_tworzy_drugiego_zakupu(tenant, provider):
    teraz = timezone.now().replace(minute=9, second=59)
    with patch("api.utils.checkout.timezone.now", return_value=teraz):
        pierwszy = create_checkout_session(tenant, "pro")
    with patch("api.utils.checkout.timezone.now", return_value=teraz + timedelta(seconds=1)):
        drugi = create_checkout_session(tenant, "pro")
    assert pierwszy == drugi
    assert len(provider.sesje) == len(provider.utworzenia) == 1


@pytest.mark.django_db
def test_zmiana_planu_najpierw_wygasza_poprzednia_sesje(tenant, provider):
    create_checkout_session(tenant, "pro")
    pierwsza = ProbaZakupu.objects.get(tenant=tenant).sesja_id

    def utworz(**params):
        assert provider.sesje[pierwsza]["status"] == "expired"
        return provider.create(**params)

    with patch("stripe.checkout.Session.create", side_effect=utworz):
        create_checkout_session(tenant, "grow")
    assert provider.wygaszenia == [pierwsza]
    assert sum(s["status"] == "open" for s in provider.sesje.values()) == 1
    assert provider.utworzenia[-1]["line_items"] == [{"price": "price_grow", "quantity": 1}]


@pytest.mark.django_db
def test_utrata_odpowiedzi_zachowuje_klucz_i_parametry(tenant, provider, settings):
    provider.zgub_odpowiedz = True
    with pytest.raises(ValidationError):
        create_checkout_session(tenant, "pro", "pierwszy@example.test")
    proba = ProbaZakupu.objects.get(tenant=tenant)
    assert proba.parametry and not proba.sesja_id
    settings.FRONTEND_URL = "https://nowy-panel.example.test"
    with patch("api.views.stripe.kartoteka_klienta", return_value=None) as kartoteka:
        create_checkout_session(tenant, "pro", "drugi@example.test")
    kartoteka.assert_not_called()
    assert provider.utworzenia[0] == provider.utworzenia[1]
    assert len(provider.sesje) == 1


@pytest.mark.django_db
def test_blad_bazy_po_utworzeniu_sesji_nie_gubi_proby(tenant, provider):
    zapis = ProbaZakupu.save

    def zapisz(self, *args, **kwargs):
        if kwargs.get("update_fields") == ["sesja_id"]:
            raise DatabaseError("zerwane połączenie po odpowiedzi Stripe")
        return zapis(self, *args, **kwargs)

    with patch.object(ProbaZakupu, "save", zapisz), pytest.raises(DatabaseError):
        create_checkout_session(tenant, "pro")
    assert ProbaZakupu.objects.get(tenant=tenant).parametry
    create_checkout_session(tenant, "pro")
    assert len(provider.sesje) == 1
    assert provider.utworzenia[0] == provider.utworzenia[1]


@pytest.mark.django_db
def test_timeout_wygaszania_nie_pozwala_od_razu_kupic_drugiego_planu(tenant, provider):
    create_checkout_session(tenant, "pro")

    def wygas(sid):
        provider.expire(sid)
        raise stripe.APIConnectionError("Odpowiedź wygaszenia nie dotarła")

    with patch("stripe.checkout.Session.expire", side_effect=wygas), pytest.raises(ValidationError):
        create_checkout_session(tenant, "grow")
    assert len(provider.sesje) == 1
    create_checkout_session(tenant, "grow")
    assert sum(s["status"] == "open" for s in provider.sesje.values()) == 1


@pytest.mark.django_db
def test_zaplaty_bez_webhooka_nie_mozna_powtorzyc(tenant, provider):
    create_checkout_session(tenant, "pro")
    sid = ProbaZakupu.objects.get(tenant=tenant).sesja_id
    provider.sesje[sid].update(status="complete", subscription="sub_paid")
    with (
        patch("stripe.Subscription.retrieve", return_value={"status": "active"}),
        pytest.raises(CheckoutZakonczony),
    ):
        create_checkout_session(tenant, "grow")
    assert len(provider.sesje) == 1


@pytest.mark.django_db
def test_zaplata_w_trakcie_zmiany_planu_nie_tworzy_drugiej_sesji(tenant, provider):
    create_checkout_session(tenant, "pro")

    def wyscig(sid):
        provider.sesje[sid].update(status="complete", subscription="sub_paid")
        return provider.expire(sid)

    with (
        patch("stripe.checkout.Session.expire", side_effect=wyscig),
        pytest.raises(ValidationError),
    ):
        create_checkout_session(tenant, "grow")
    assert len(provider.sesje) == 1


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["canceled", "incomplete_expired"])
def test_nowy_zakup_po_rzeczywistym_zakonczeniu_subskrypcji(tenant, provider, status):
    create_checkout_session(tenant, "pro")
    sid = ProbaZakupu.objects.get(tenant=tenant).sesja_id
    provider.sesje[sid].update(status="complete", subscription="sub_ended")
    with patch("stripe.Subscription.retrieve", return_value={"status": status}):
        create_checkout_session(tenant, "grow")
    assert len(provider.sesje) == 2


@pytest.mark.django_db
def test_nieznany_wynik_po_23h_wymaga_uzgodnienia(tenant, provider):
    provider.zgub_odpowiedz = True
    with pytest.raises(ValidationError):
        create_checkout_session(tenant, "pro")
    ProbaZakupu.objects.filter(tenant=tenant).update(
        rozpoczeta_at=timezone.now() - timedelta(hours=24)
    )
    with pytest.raises(CheckoutDoWyjasnienia):
        create_checkout_session(tenant, "grow")
    assert len(provider.utworzenia) == len(provider.sesje) == 1


@pytest.mark.django_db
@pytest.mark.parametrize("aktualny", ["complete", "expired"])
def test_replay_create_nie_jest_aktualnym_stanem_sesji(tenant, provider, aktualny):
    provider.zgub_odpowiedz = True
    with pytest.raises(ValidationError):
        create_checkout_session(tenant, "pro")
    sid = next(iter(provider.sesje))
    provider.sesje[sid].update(status=aktualny, subscription="sub_paid")
    # Atrapa odtwarza odpowiedź pierwszego create (open), nie aktualny stan.
    with patch("stripe.Subscription.retrieve", return_value={"status": "active"}):
        if aktualny == "complete":
            with pytest.raises(CheckoutZakonczony):
                create_checkout_session(tenant, "grow")
            assert len(provider.sesje) == 1
        else:
            create_checkout_session(tenant, "grow")
            assert len(provider.sesje) == 2
            assert sum(s["status"] == "open" for s in provider.sesje.values()) == 1


@pytest.mark.django_db
def test_wygasla_sesja_dostaje_nowy_klucz(tenant, provider):
    create_checkout_session(tenant, "pro")
    proba = ProbaZakupu.objects.get(tenant=tenant)
    provider.expire(proba.sesja_id)
    create_checkout_session(tenant, "pro")
    assert ProbaZakupu.objects.get(tenant=tenant).klucz != proba.klucz
    assert len(provider.sesje) == 2


@pytest.mark.django_db(transaction=True)
def test_dwie_karty_nie_tworza_dwoch_sesji(tenant, provider):
    wszedl, zwolnij = Event(), Event()

    def odczyt():
        close_old_connections()
        try:
            return bool(ProbaZakupu.objects.get(tenant_id=tenant.pk).parametry)
        finally:
            connections.close_all()

    def wstrzymany(**kwargs):
        with ThreadPoolExecutor(max_workers=1) as czytelnik:
            assert czytelnik.submit(odczyt).result(timeout=5)
        wszedl.set()
        assert zwolnij.wait(10)
        return provider.create(**kwargs)

    def pierwsza_karta():
        close_old_connections()
        try:
            return create_checkout_session(tenant, "pro")
        finally:
            connections.close_all()

    with (
        patch("stripe.checkout.Session.create", side_effect=wstrzymany),
        ThreadPoolExecutor(max_workers=1) as pula,
    ):
        wynik = pula.submit(pierwsza_karta)
        try:
            assert wszedl.wait(10)
            with pytest.raises(CheckoutZajety):
                create_checkout_session(tenant, "grow")
        finally:
            zwolnij.set()
        assert wynik.result(timeout=10).startswith("https://checkout.stripe.test/")
    assert len(provider.sesje) == 1


@pytest.mark.django_db(transaction=True)
def test_transakcja_nadrzedna_nie_moze_cofnac_proby_po_stripe(tenant, provider):
    with transaction.atomic(), pytest.raises(RuntimeError, match="durable"):
        create_checkout_session(tenant, "pro")
    assert not provider.utworzenia


@pytest.mark.django_db
def test_migracja_zaznacza_istniejace_firmy_do_kontroli(tenant):
    from importlib import import_module
    from types import SimpleNamespace

    from django.apps import apps
    from django.db import connection

    migracja = import_module("accounts.migrations.0041_proba_zakupu")
    migracja.oznacz_istniejace_firmy(apps, SimpleNamespace(connection=connection))
    assert not ProbaZakupu.objects.get(tenant=tenant).sprawdzone_stare_sesje


@pytest.mark.django_db
def test_sesje_sprzed_migracji_sa_wygaszane_takze_bez_customer(tenant, provider):
    ProbaZakupu.objects.create(tenant=tenant, sprawdzone_stare_sesje=False)
    stara = {
        "id": "cs_old",
        "mode": "subscription",
        "status": "open",
        "metadata": {"tenant_id": str(tenant.pk)},
    }
    obca = {**stara, "id": "cs_other", "metadata": {"tenant_id": "999999"}}
    provider.sesje.update({stara["id"]: stara, obca["id"]: obca})
    with patch(
        "stripe.checkout.Session.list", return_value={"data": [obca, stara], "has_more": False}
    ):
        create_checkout_session(tenant, "pro")
    assert provider.wygaszenia == ["cs_old"]
    assert provider.sesje[obca["id"]]["status"] == "open"
    assert ProbaZakupu.objects.get(tenant=tenant).sprawdzone_stare_sesje


@pytest.mark.django_db
def test_zaplacona_stara_sesja_blokuje_zakup(tenant, provider):
    ProbaZakupu.objects.create(tenant=tenant, sprawdzone_stare_sesje=False)
    stara = {
        "id": "cs_old",
        "mode": "subscription",
        "status": "complete",
        "subscription": "sub_old",
        "metadata": {"tenant_id": str(tenant.pk)},
    }
    with (
        patch("stripe.checkout.Session.list", return_value={"data": [stara], "has_more": False}),
        patch("stripe.Subscription.retrieve", return_value={"status": "active"}),
        pytest.raises(CheckoutZakonczony),
    ):
        create_checkout_session(tenant, "pro")
    assert not provider.utworzenia


@pytest.mark.django_db
def test_niepelny_przeglad_starych_sesji_nie_odblokowuje_zakupu(tenant, provider):
    ProbaZakupu.objects.create(tenant=tenant, sprawdzone_stare_sesje=False)
    with (
        patch(
            "stripe.checkout.Session.list",
            return_value={"data": [{"id": "cs_other"}], "has_more": True},
        ) as lista,
        pytest.raises(CheckoutDoWyjasnienia),
    ):
        create_checkout_session(tenant, "pro")
    assert lista.call_count == 5
    assert not provider.utworzenia


@pytest.mark.django_db
def test_rozne_firmy_maja_odrebne_proby(tenant, provider):
    druga = Tenant.objects.create(name="Druga", owner_email="druga@example.test")
    create_checkout_session(tenant, "pro")
    create_checkout_session(druga, "pro")
    assert len(provider.sesje) == ProbaZakupu.objects.count() == 2


@pytest.mark.django_db
def test_uzgodnienie_po_utracie_odpowiedzi_jest_domyslnie_tylko_odczytem(
    tenant, provider, settings
):
    from django.core.management import call_command

    settings.STRIPE_SECRET_KEY = "synthetic-test-key"
    provider.zgub_odpowiedz = True
    with pytest.raises(ValidationError):
        create_checkout_session(tenant, "pro")
    sid = next(iter(provider.sesje))
    ProbaZakupu.objects.filter(tenant=tenant).update(
        rozpoczeta_at=timezone.now() - timedelta(days=2)
    )
    call_command("uzgodnij_checkout", tenant=tenant.pk, sesja=sid)
    assert not ProbaZakupu.objects.get(tenant=tenant).sesja_id
    call_command("uzgodnij_checkout", tenant=tenant.pk, sesja=sid, zapisz=True)
    create_checkout_session(tenant, "pro")
    assert len(provider.utworzenia) == 1


@pytest.mark.django_db
@pytest.mark.parametrize("pole", ["tenant_id", "checkout_attempt"])
def test_uzgodnienie_nie_przypina_cudzej_lub_poprzedniej_proby(tenant, provider, settings, pole):
    from django.core.management import CommandError, call_command

    settings.STRIPE_SECRET_KEY = "synthetic-test-key"
    provider.zgub_odpowiedz = True
    with pytest.raises(ValidationError):
        create_checkout_session(tenant, "pro")
    sid = next(iter(provider.sesje))
    provider.sesje[sid]["metadata"][pole] = "inna"
    with pytest.raises(CommandError):
        call_command("uzgodnij_checkout", tenant=tenant.pk, sesja=sid, zapisz=True)
    assert not ProbaZakupu.objects.get(tenant=tenant).sesja_id
