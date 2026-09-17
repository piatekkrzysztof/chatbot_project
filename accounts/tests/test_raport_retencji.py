"""
Raport retencji: ma mówić to samo, co zrobi nocne zadanie.

Kategoria ryzyka: DECYZJA NA PODSTAWIE FIKCJI. Ten raport jest jedynym
podglądem przed operacją, której nie da się cofnąć. Liczba inna niż ta, którą
zabierze sprzątanie, byłaby gorsza niż brak raportu - dawałaby spokój.

Reguły siedzą w `accounts/retencja.py` i sprawdza je `test_retencja.py`.
Tutaj pilnujemy dwóch rzeczy: że raport czyta z tego samego miejsca, i że
niczego nie rusza.
"""

import io
import re
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from accounts import retencja
from accounts.models import WpisDziennika
from accounts.sessions import LoginSession

pytestmark = pytest.mark.django_db

LICZBA_DO_USUNIECIA = re.compile(r"do usunięcia przy najbliższym przebiegu: (\d+)")


def raport():
    strumien = io.StringIO()
    call_command("raport_retencji", stdout=strumien)
    return strumien.getvalue()


def stary_wpis_dziennika():
    wpis = WpisDziennika.objects.create(metoda="DELETE", sciezka="/api/faq/1/", status=204)
    WpisDziennika.objects.filter(pk=wpis.pk).update(
        czas=timezone.now() - retencja.OKRESY["dziennik"] - timedelta(hours=1)
    )
    return wpis


def test_liczby_zgadzaja_sie_z_regulami(user):
    stary_wpis_dziennika()
    LoginSession.objects.create(
        user=user,
        password_fingerprint="x" * 64,
        expires_at=timezone.now() - retencja.OKRESY["sesje"] - timedelta(hours=1),
    )

    tresc = raport()

    wypisane = [int(x) for x in LICZBA_DO_USUNIECIA.findall(tresc)]
    z_regul = [retencja.do_usuniecia(klucz).count() for klucz in retencja.REGULY]
    assert wypisane == z_regul
    assert sum(wypisane) == 2


def test_raport_niczego_nie_usuwa(user):
    stary_wpis_dziennika()

    raport()

    assert WpisDziennika.objects.count() == 1


def test_raport_wymienia_wszystkie_rodzaje_danych():
    # Rodzaj pominięty w wypisie to rodzaj, o którym nikt nie pomyśli przy
    # kolejnej zmianie okresów - a usuwanie i tak będzie go dotyczyć.
    tresc = raport()

    for nazwa in retencja.NAZWY.values():
        assert nazwa in tresc


def test_pusta_baza_nie_wywraca_raportu():
    assert "Raport retencji" in raport()
