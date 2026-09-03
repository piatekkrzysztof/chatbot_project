"""
Dane do faktury po stronie Stripe.

Kategoria ryzyka: PIENIĄDZE i DOKUMENTY. Polska firma bez NIP-u na fakturze
nie wrzuci jej w koszty - czyli dostaje dokument, który jest jej do niczego,
i przy każdej płatności musi prosić nas o korektę.

Drugie ryzyko jest w drugą stronę i ważniejsze: żadna z tych wygód nie może
zablokować zapłaty. Klient, który nie może kupić, kosztuje więcej niż faktura
bez adresu.
"""

from unittest.mock import MagicMock, patch

import pytest
import stripe

from accounts.models import DaneRozliczeniowe, Tenant
from api.utils.stripe_klient import kartoteka_klienta


@pytest.fixture
def firma(db):
    return Tenant.objects.create(name="Rowerownia", owner_email="szef@rowerownia.pl")


@pytest.fixture
def dane(firma):
    return DaneRozliczeniowe.objects.create(
        tenant=firma,
        nazwa="Rowerownia Krakowska Anna Nowak",
        nip="5260250274",
        ulica="Krakowska 12",
        kod_pocztowy="31-000",
        miasto="Kraków",
        kraj="PL",
    )


@pytest.fixture
def pusta_lista_nipow():
    """Kartoteka bez przypiętych identyfikatorów podatkowych."""
    lista = MagicMock()
    lista.data = []
    return lista


@pytest.mark.django_db
class TestZakladaniaKartoteki:
    def test_dane_z_rejestracji_ida_do_stripe(self, firma, dane, pusta_lista_nipow):
        """
        Sedno całej zmiany.

        Pytamy klienta o nazwe, adres i NIP „zeby bylo do faktury", po czym do
        Stripe'a szedl z tego wylacznie e-mail. Te pola musza dojechac.
        """
        klient = MagicMock(id="cus_test123")

        with (
            patch("stripe.Customer.create", return_value=klient) as utworz,
            patch("stripe.Customer.list_tax_ids", return_value=pusta_lista_nipow),
            patch("stripe.Customer.create_tax_id"),
        ):
            wynik = kartoteka_klienta(firma)

        assert wynik == "cus_test123"
        przekazane = utworz.call_args.kwargs
        assert przekazane["name"] == "Rowerownia Krakowska Anna Nowak"
        assert przekazane["address"]["line1"] == "Krakowska 12"
        assert przekazane["address"]["postal_code"] == "31-000"
        assert przekazane["address"]["city"] == "Kraków"
        assert przekazane["address"]["country"] == "PL"

    def test_nip_przypina_sie_z_przedrostkiem_kraju(self, firma, dane, pusta_lista_nipow):
        # Stripe nie ma typu "polski NIP" - firmy z Unii ida jako eu_vat
        # z przedrostkiem kraju. Sam numer bez PL zostalby odrzucony.
        with (
            patch("stripe.Customer.create", return_value=MagicMock(id="cus_1")),
            patch("stripe.Customer.list_tax_ids", return_value=pusta_lista_nipow),
            patch("stripe.Customer.create_tax_id") as przypnij,
        ):
            kartoteka_klienta(firma)

        assert przypnij.call_args.kwargs["value"] == "PL5260250274"
        assert przypnij.call_args.kwargs["type"] == "eu_vat"

    def test_identyfikator_zapisuje_sie_przy_firmie(self, firma, dane, pusta_lista_nipow):
        """
        Pole `stripe_customer_id` istnialo w modelu od dawna i NIC go nigdy nie
        zapisywalo. Skutek: kazdy zakup zakladal nowa, anonimowa kartoteke,
        a historia platnosci jednej firmy rozsypywala sie po wielu.
        """
        with (
            patch("stripe.Customer.create", return_value=MagicMock(id="cus_nowy")),
            patch("stripe.Customer.list_tax_ids", return_value=pusta_lista_nipow),
            patch("stripe.Customer.create_tax_id"),
        ):
            kartoteka_klienta(firma)

        firma.refresh_from_db()
        assert firma.stripe_customer_id == "cus_nowy"

    def test_konto_bez_danych_rozliczeniowych_dostaje_nazwe_firmy(self, firma):
        # Konta sprzed wprowadzenia tych pol nie maja wiersza z danymi.
        # Kartoteka ma powstac mimo to - inaczej starzy klienci nie mogliby
        # kupic planu.
        with patch("stripe.Customer.create", return_value=MagicMock(id="cus_2")) as utworz:
            wynik = kartoteka_klienta(firma)

        assert wynik == "cus_2"
        assert utworz.call_args.kwargs["name"] == "Rowerownia"
        assert "address" not in utworz.call_args.kwargs

    def test_niekompletny_adres_nie_jest_wysylany(self, firma, pusta_lista_nipow):
        """
        Adres w polowie pusty wyglada na fakturze gorzej niz jego brak -
        i wyglada przy tym na dane, a nie na brak danych.
        """
        DaneRozliczeniowe.objects.create(
            tenant=firma, nazwa="Rowerownia", nip="", ulica="", kod_pocztowy="", miasto=""
        )

        with (
            patch("stripe.Customer.create", return_value=MagicMock(id="cus_3")) as utworz,
            patch("stripe.Customer.list_tax_ids", return_value=pusta_lista_nipow),
        ):
            kartoteka_klienta(firma)

        assert "address" not in utworz.call_args.kwargs


@pytest.mark.django_db
class TestOdswiezania:
    def test_kolejny_zakup_odswieza_kartoteke_zamiast_zakladac_nowa(
        self, firma, dane, pusta_lista_nipow
    ):
        firma.stripe_customer_id = "cus_istniejacy"
        firma.save()

        with (
            patch("stripe.Customer.modify", return_value=MagicMock(id="cus_istniejacy")) as zmien,
            patch("stripe.Customer.create") as utworz,
            patch("stripe.Customer.list_tax_ids", return_value=pusta_lista_nipow),
            patch("stripe.Customer.create_tax_id"),
        ):
            kartoteka_klienta(firma)

        # Zmiana adresu w panelu ma dojechac do Stripe przy nastepnej platnosci.
        assert zmien.call_args.args[0] == "cus_istniejacy"
        assert utworz.call_count == 0

    def test_nip_nie_dokleja_sie_drugi_raz(self, firma, dane):
        # Stripe trzyma identyfikatory podatkowe jako liste. Bez sprawdzenia,
        # co juz jest, kazde wejscie do platnosci doklejaloby ten sam numer.
        firma.stripe_customer_id = "cus_istniejacy"
        firma.save()

        istniejace = MagicMock()
        istniejace.data = [MagicMock(value="PL5260250274")]

        with (
            patch("stripe.Customer.modify", return_value=MagicMock(id="cus_istniejacy")),
            patch("stripe.Customer.list_tax_ids", return_value=istniejace),
            patch("stripe.Customer.create_tax_id") as przypnij,
        ):
            kartoteka_klienta(firma)

        assert przypnij.call_count == 0

    def test_skasowana_kartoteka_odtwarza_sie(self, firma, dane, pusta_lista_nipow):
        """
        Kartoteka skasowana recznie w panelu Stripe albo zapisana w trybie
        testowym przy kluczu produkcyjnym. Klient nie moze przez to utknac
        na zawsze bez mozliwosci zaplacenia.
        """
        firma.stripe_customer_id = "cus_nieistniejacy"
        firma.save()

        with (
            patch(
                "stripe.Customer.modify",
                side_effect=stripe.error.InvalidRequestError("No such customer", None),
            ),
            patch("stripe.Customer.create", return_value=MagicMock(id="cus_odtworzony")),
            patch("stripe.Customer.list_tax_ids", return_value=pusta_lista_nipow),
            patch("stripe.Customer.create_tax_id"),
        ):
            wynik = kartoteka_klienta(firma)

        assert wynik == "cus_odtworzony"
        firma.refresh_from_db()
        assert firma.stripe_customer_id == "cus_odtworzony"


@pytest.mark.django_db
class TestZeNicNieBlokujeZaplaty:
    """Najważniejsza klasa w tym pliku."""

    def test_awaria_przypinania_nipu_nie_przerywa(self, firma, dane):
        """
        Faktura bez NIP-u jest klopotem. Klient, ktory nie moze zaplacic, jest
        klopotem wiekszym - i naszym.
        """
        with (
            patch("stripe.Customer.create", return_value=MagicMock(id="cus_4")),
            patch(
                "stripe.Customer.list_tax_ids",
                side_effect=stripe.error.StripeError("cos poszlo nie tak"),
            ),
        ):
            wynik = kartoteka_klienta(firma)

        assert wynik == "cus_4"

    def test_awaria_kartoteki_zwraca_none_zamiast_wyjatku(self, firma, dane):
        # Wywolujacy ma wtedy wrocic do samego adresu e-mail, a nie pokazac
        # klientowi bledu przy probie zaplacenia.
        with patch(
            "stripe.Customer.create",
            side_effect=stripe.error.StripeError("Stripe niedostepny"),
        ):
            assert kartoteka_klienta(firma) is None


@pytest.mark.django_db
class TestSesjiPlatnosci:
    def test_sesja_uzywa_kartoteki_zamiast_samego_emaila(self, firma, dane):
        from api.views.stripe import create_checkout_session

        with (
            patch("api.views.stripe.kartoteka_klienta", return_value="cus_test"),
            patch(
                "stripe.checkout.Session.create",
                return_value=MagicMock(url="https://checkout.stripe.com/x"),
            ) as sesja,
        ):
            create_checkout_session(firma, "start", email="szef@rowerownia.pl")

        przekazane = sesja.call_args.kwargs
        assert przekazane["customer"] == "cus_test"
        # Stripe odrzuca sesje, ktora podaje jednoczesnie kartoteke i e-mail.
        assert "customer_email" not in przekazane

    def test_bez_kartoteki_platnosc_idzie_po_emailu(self, firma, dane):
        """
        Droga awaryjna. Gdyby jej nie bylo, awaria po stronie Stripe przy
        zakladaniu kartoteki zabieralaby klientowi mozliwosc zaplacenia -
        czyli wygoda ksiegowa kosztowalaby sprzedaz.
        """
        from api.views.stripe import create_checkout_session

        with (
            patch("api.views.stripe.kartoteka_klienta", return_value=None),
            patch(
                "stripe.checkout.Session.create",
                return_value=MagicMock(url="https://checkout.stripe.com/x"),
            ) as sesja,
        ):
            create_checkout_session(firma, "start", email="szef@rowerownia.pl")

        przekazane = sesja.call_args.kwargs
        assert przekazane["customer_email"] == "szef@rowerownia.pl"
        assert "customer" not in przekazane
