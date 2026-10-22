"""
Wygasłe tokeny odświeżania znikają w nocnej retencji (2.32.11).

SimpleJWT zapisuje każdy wydany token odświeżania (pełny JWT z identyfikatorem
konta) i każdy unieważniony. Panel odświeża sesję co 15 minut, więc przybywa
wiersz za wierszem, a nic ich nie usuwało: `docs/odwolywanie-sesji.md`
wymagało `flushexpiredtokens` w harmonogramie, którego tam nigdy nie było,
a tabeli brakowało w inwentarzu danych (audyt 2026-10, P13).

Wygasły token nie otwiera niczego - odrzuca go już podpis z datą ważności -
więc jego wiersz na liście unieważnionych też nie jest potrzebny.
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from accounts import retencja
from accounts.models import CustomUser, Tenant
from api.session_tokens import SessionRefreshToken

pytestmark = pytest.mark.django_db


@pytest.fixture
def konto():
    firma = Tenant.objects.create(name="Tokeny")
    return CustomUser.objects.create_user(username="tokeny", email="t@example.com", tenant=firma)


def token_wygasly(konto, ile_temu):
    token = SessionRefreshToken.for_user(konto)
    OutstandingToken.objects.filter(jti=token["jti"]).update(expires_at=timezone.now() - ile_temu)
    return OutstandingToken.objects.get(jti=token["jti"])


def test_wygasly_dawniej_niz_doba_znika(konto):
    stary = token_wygasly(konto, timedelta(days=1, minutes=1))

    assert retencja.usun("tokeny_odswiezania") == 1
    assert not OutstandingToken.objects.filter(pk=stary.pk).exists()


def test_wygasly_niedawno_i_wazny_zostaja(konto):
    swiezo_wygasly = token_wygasly(konto, timedelta(hours=23))
    wazny = OutstandingToken.objects.get(jti=SessionRefreshToken.for_user(konto)["jti"])

    assert retencja.usun("tokeny_odswiezania") == 0
    assert OutstandingToken.objects.filter(pk__in=[swiezo_wygasly.pk, wazny.pk]).count() == 2


def test_wpis_na_liscie_uniewaznionych_znika_razem_z_tokenem(konto):
    stary = token_wygasly(konto, timedelta(days=30))
    BlacklistedToken.objects.create(token=stary)

    retencja.usun("tokeny_odswiezania")

    assert not BlacklistedToken.objects.filter(token_id=stary.pk).exists()


def test_proba_tylko_liczy(konto):
    stary = token_wygasly(konto, timedelta(days=30))

    assert retencja.usun("tokeny_odswiezania", proba=True) == 1
    assert OutstandingToken.objects.filter(pk=stary.pk).exists()


def test_nocne_sprzatanie_obejmuje_tokeny(konto):
    token_wygasly(konto, timedelta(days=30))

    wynik = retencja.usun_wszystko()

    assert wynik["tokeny_odswiezania"] == 1
