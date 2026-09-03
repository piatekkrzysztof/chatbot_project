"""
Kartoteka klienta w Stripe, zbudowana z danych, które i tak zbieramy.

Przy rejestracji pytamy o pełną nazwę, NIP i adres - „żeby było do faktury
i umowy". Do Stripe'a szedł z tego wyłącznie adres e-mail. Polska firma
dostawała więc fakturę bez własnego NIP-u, czyli dokument, którego nie wrzuci
w koszty, i musiała prosić nas o korektę przy każdej płatności.

Druga rzecz, którą to naprawia: `customer_email` bez identyfikatora klienta
każe Stripe'owi zakładać nową kartotekę przy każdym zakupie. Pole
`Tenant.stripe_customer_id` istniało w modelu od dawna i nic go nigdy nie
zapisywało ani nie czytało, więc historia płatności jednej firmy rozsypywała
się po wielu kartotekach - a przy odnowieniach nie było jak jej złożyć.

Zasada: dane w naszym panelu są źródłem prawdy. Każde wejście do płatności
odświeża kartotekę w Stripe, zamiast pozwalać obu stronom rozjeżdżać się
w swoim tempie.
"""

import logging

import stripe

from accounts.models import DaneRozliczeniowe

logger = logging.getLogger(__name__)

#: Typ identyfikatora podatkowego dla polskiego NIP-u.
#:
#: Stripe nie ma osobnego typu „polski NIP" - firmy z Unii idą jako `eu_vat`
#: z przedrostkiem kraju. Numer jest sprawdzany przez VIES asynchronicznie,
#: więc firma spoza rejestru VAT-UE dostanie go na fakturze jako
#: niezweryfikowany. To jest wciąż o klasę lepsze niż faktura bez NIP-u.
TYP_NIP = "eu_vat"


def _adres(dane: DaneRozliczeniowe) -> dict | None:
    """
    Adres tylko wtedy, gdy jest kompletny.

    Konta założone przed wprowadzeniem tych pól mają puste ulice i miasta.
    Wysłanie takiego adresu zapisałoby w Stripe pustą kartotekę, która na
    fakturze wygląda gorzej niż brak adresu - i wygląda przy tym na dane,
    a nie na brak danych.
    """
    if not (dane.ulica and dane.kod_pocztowy and dane.miasto):
        return None

    return {
        "line1": dane.ulica,
        "postal_code": dane.kod_pocztowy,
        "city": dane.miasto,
        "country": (dane.kraj or "PL").upper(),
    }


def _przypnij_nip(identyfikator: str, dane: DaneRozliczeniowe) -> None:
    """
    Dokłada NIP do kartoteki, jeśli jeszcze go tam nie ma.

    Osobne wywołanie, bo Stripe trzyma identyfikatory podatkowe jako listę
    powiązaną z klientem, a nie jako pole. Bez sprawdzenia, co już jest,
    każde wejście do płatności doklejałoby ten sam numer jeszcze raz.

    Cała funkcja jest miękka: nieudane przypięcie NIP-u NIE MOŻE zatrzymać
    płatności. Faktura bez NIP-u jest kłopotem, ale klient, który nie może
    zapłacić, jest kłopotem większym - i naszym.
    """
    if not dane.nip:
        return

    wartosc = f"{(dane.kraj or 'PL').upper()}{dane.nip}"

    try:
        istniejace = stripe.Customer.list_tax_ids(identyfikator, limit=20)
        if any(wpis.value == wartosc for wpis in istniejace.data):
            return

        stripe.Customer.create_tax_id(identyfikator, type=TYP_NIP, value=wartosc)
    except stripe.error.StripeError:
        logger.warning(
            "Nie udalo sie przypiac NIP-u do kartoteki %s - platnosc idzie dalej",
            identyfikator,
            exc_info=True,
        )


def kartoteka_klienta(tenant, email: str | None = None) -> str | None:
    """
    Zwraca identyfikator klienta Stripe dla firmy, tworząc go przy pierwszym
    zakupie i odświeżając przy każdym kolejnym.

    Zwraca `None`, gdy Stripe odmówił - wywołujący ma wtedy wrócić do samego
    adresu e-mail. Płatność bez pełnych danych na fakturze jest gorsza od
    płatności z nimi, ale nieporównanie lepsza od braku możliwości zapłacenia.
    """
    dane = DaneRozliczeniowe.objects.filter(tenant=tenant).first()

    pola = {
        "name": (dane.nazwa if dane and dane.nazwa else tenant.name),
        "email": email or tenant.owner_email,
        "metadata": {"tenant_id": str(tenant.id)},
    }

    adres = _adres(dane) if dane else None
    if adres:
        pola["address"] = adres

    try:
        if tenant.stripe_customer_id:
            # Modyfikacja, a nie odczyt: przy okazji dosyla zmiany wprowadzone
            # w panelu od poprzedniej platnosci. Skasowana po naszej stronie
            # kartoteka konczy sie bledem, ktory lapiemy nizej.
            klient = stripe.Customer.modify(tenant.stripe_customer_id, **pola)
        else:
            klient = stripe.Customer.create(**pola)
            tenant.stripe_customer_id = klient.id
            tenant.save(update_fields=["stripe_customer_id"])
    except stripe.error.InvalidRequestError:
        # Najczestszy przypadek: kartoteka skasowana recznie w panelu Stripe
        # albo zapisana w trybie testowym, a klucz jest produkcyjny. Zakladamy
        # nowa zamiast odbijac klienta od platnosci.
        logger.warning(
            "Kartoteka %s nieosiagalna - zakladam nowa dla firmy %s",
            tenant.stripe_customer_id,
            tenant.id,
            exc_info=True,
        )
        try:
            klient = stripe.Customer.create(**pola)
            tenant.stripe_customer_id = klient.id
            tenant.save(update_fields=["stripe_customer_id"])
        except stripe.error.StripeError:
            logger.exception("Nie udalo sie zalozyc kartoteki dla firmy %s", tenant.id)
            return None
    except stripe.error.StripeError:
        logger.exception("Stripe odmowil obslugi kartoteki firmy %s", tenant.id)
        return None

    if dane:
        _przypnij_nip(klient.id, dane)

    return klient.id
