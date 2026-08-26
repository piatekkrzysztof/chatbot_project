"""
Powiadomienia o koncu subskrypcji.

Kategoria ryzyka: CICHA AWARIA. Wygasla subskrypcja wycisza chatbota tak samo
jak wyczerpany limit wiadomosci, ale przez dlugi czas nie miala zadnego
powiadomienia. Zdarzylo sie to naprawde: okres probny skonczyl sie w niedziele,
widget zamilkl, a wlasciciel dowiedzial sie o tym przypadkiem, kilka dni
pozniej -- i przez ten czas kazdy odwiedzajacy jego strone dostawal komunikat
o bledzie zamiast odpowiedzi.

Testy pilnuja obu polowek: ze wiadomosc idzie wtedy, kiedy trzeba, ORAZ ze nie
idzie wtedy, kiedy nie trzeba. Sam pierwszy warunek przepuscilby zadanie
wysylajace codziennie, a klient nauczylby sie ignorowac te wiadomosci dokladnie
wtedy, gdy zaczynaja byc wazne.
"""
from datetime import date, timedelta

import pytest
from django.core import mail

from accounts.models import Subscription, Tenant
from accounts.tasks_konce import sprawdz_konce_subskrypcji


@pytest.fixture
def firma(db):
    return Tenant.objects.create(name="Rowerownia Krakowska", owner_email="szef@rowerownia.pl")


def subskrypcja(firma, konczy_za_dni, **pola):
    dzisiaj = date.today()
    return Subscription.objects.create(
        tenant=firma,
        plan_type="start",
        start_date=dzisiaj - timedelta(days=30),
        end_date=dzisiaj + timedelta(days=konczy_za_dni),
        is_active=True,
        **pola,
    )


@pytest.mark.django_db
class TestUprzedzenia:
    def test_trzy_dni_przed_koncem_leci_ostrzezenie(self, firma):
        subskrypcja(firma, konczy_za_dni=3)

        assert sprawdz_konce_subskrypcji() == 1
        assert "3 dni" in mail.outbox[0].subject
        assert mail.outbox[0].to == ["szef@rowerownia.pl"]

    def test_daleko_od_konca_nic_nie_leci(self, firma):
        # Bez tego wlasciciel dostawalby wiadomosc codziennie przez caly cykl.
        subskrypcja(firma, konczy_za_dni=20)

        assert sprawdz_konce_subskrypcji() == 0
        assert mail.outbox == []


@pytest.mark.django_db
class TestWygasniecia:
    def test_po_koncu_leci_informacja_ze_bot_milczy(self, firma):
        subskrypcja(firma, konczy_za_dni=-1)

        sprawdz_konce_subskrypcji()

        assert "wygasła" in mail.outbox[0].subject
        assert "nie odpowiada" in mail.outbox[0].subject

    def test_tresc_mowi_co_widzi_odwiedzajacy(self, firma):
        # Wlasciciel musi wiedziec, ze problem jest widoczny dla jego klientow,
        # a nie tylko dla niego w panelu. To ta informacja zamienia komunikat
        # w decyzje.
        subskrypcja(firma, konczy_za_dni=-1)

        sprawdz_konce_subskrypcji()

        assert "odwiedzającym" in mail.outbox[0].body

    def test_przeskok_daje_jedna_wiadomosc_o_wygasnieciu(self, firma):
        # Gdy zadanie nie chodzilo przez tydzien, wlasciciel ma dostac
        # "subskrypcja wygasla", a nie najpierw ostrzezenie o czyms,
        # co juz sie stalo.
        subskrypcja(firma, konczy_za_dni=-5)

        assert sprawdz_konce_subskrypcji() == 1
        assert "wygasła" in mail.outbox[0].subject


@pytest.mark.django_db
class TestPowtorzen:
    def test_ta_sama_wiadomosc_nie_leci_drugi_raz(self, firma):
        subskrypcja(firma, konczy_za_dni=-1)

        sprawdz_konce_subskrypcji()
        mail.outbox.clear()

        assert sprawdz_konce_subskrypcji() == 0
        assert mail.outbox == []

    def test_po_ostrzezeniu_wciaz_przychodzi_wiadomosc_o_wygasnieciu(self, firma):
        # Dwa rozne zdarzenia, nie powtorzenie jednego.
        sub = subskrypcja(firma, konczy_za_dni=2)
        sprawdz_konce_subskrypcji()
        mail.outbox.clear()

        sub.end_date = date.today() - timedelta(days=1)
        sub.save(update_fields=["end_date"])

        assert sprawdz_konce_subskrypcji() == 1
        assert "wygasła" in mail.outbox[0].subject

    def test_odnowienie_zeruje_licznik_powiadomien(self, firma):
        """
        Najwazniejszy test w tym pliku.

        Bez powiazania znacznika z data konca klient, ktory raz dostal komplet
        powiadomien, nie dostalby ich juz nigdy -- czyli ta sama cicha awaria
        wracalaby przy kazdym kolejnym cyklu, tyle ze bez ostrzezenia.
        """
        sub = subskrypcja(firma, konczy_za_dni=-1)
        sprawdz_konce_subskrypcji()
        mail.outbox.clear()

        # Odnowienie o rok
        sub.end_date = date.today() + timedelta(days=365)
        sub.save(update_fields=["end_date"])
        assert sprawdz_konce_subskrypcji() == 0

        # I kolejny koniec, rok pozniej
        sub.end_date = date.today() + timedelta(days=2)
        sub.save(update_fields=["end_date"])

        assert sprawdz_konce_subskrypcji() == 1
        assert "3 dni" in mail.outbox[0].subject


@pytest.mark.django_db
class TestOdpornosci:
    def test_firma_bez_adresu_nie_zatrzymuje_przegladu(self, firma):
        # Jedna firma bez adresu e-mail nie moze sprawic, ze pozostale
        # nie dostana swoich powiadomien.
        bez_adresu = Tenant.objects.create(name="Bez adresu", owner_email="")
        subskrypcja(bez_adresu, konczy_za_dni=-1)
        subskrypcja(firma, konczy_za_dni=-1)

        assert sprawdz_konce_subskrypcji() == 1
        assert [w.to for w in mail.outbox] == [["szef@rowerownia.pl"]]

    def test_firma_bez_adresu_nie_jest_sprawdzana_w_kolko(self, firma):
        # Znacznik zapisujemy takze po nieudanej wysylce, inaczej ta firma
        # generowalaby wpis w logu kazdego dnia az do konca swiata.
        bez_adresu = Tenant.objects.create(name="Bez adresu", owner_email="")
        sub = subskrypcja(bez_adresu, konczy_za_dni=-1)

        sprawdz_konce_subskrypcji()
        sub.refresh_from_db()

        assert sub.alert_konca_prog == 0
        assert sub.alert_konca_dla == sub.end_date
